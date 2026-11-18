"""Run the experiment matrix and write raw CSV files to results/raw/.

    python experiments/run_experiments.py                       # everything, 10 trials per cell
    python experiments/run_experiments.py --scenarios S1_latency --trials 3   # quick look
    python experiments/analyze.py                               # tables + figures afterwards

Needs a running MQTT broker WITH set_tcp_nodelay (default port 1883), and for
the Nagle ablation (S0) a second broker WITHOUT it (default port 1885):

    mosquitto -c config/mosquitto.conf                 # port 1883, nodelay on
    tools/mosquitto/run_mosquitto.sh 1885 false        # Linux helper, nodelay off

Trials run in parallel worker processes (default 12); every trial has its own
robot server, impairment proxy and client, so they do not interfere.
"""

from __future__ import annotations

import argparse
import csv
import json
import multiprocessing as mp
import os
import platform
import socket
import sys
import time
import traceback
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from experiments.scenarios import CONDITIONS, SCENARIOS, TRANSPORTS, Trial  # noqa: E402

RAW = os.path.join(ROOT, "results", "raw")
TRACES = os.path.join(ROOT, "results", "traces")


def build_trials(scenarios, n, broker_port, nagle_port):
    trials, uid = [], int(time.time()) % 100000 * 1000
    for sc in scenarios:
        if sc == "S0_nagle":
            for broker_nd, port in ((True, broker_port), (False, nagle_port)):
                for client_nd in (True, False):
                    for i in range(n):
                        uid += 1
                        trials.append(Trial(sc, "mqtt_q1", "C0_ideal", i, uid, port,
                                            {"broker_nodelay": broker_nd, "client_nodelay": client_nd}))
            continue
        conds = ["C1_50ms"] if sc == "S4_outage" else list(CONDITIONS)
        for tr in TRANSPORTS:
            for cond in conds:
                for i in range(n):
                    uid += 1
                    trials.append(Trial(sc, tr, cond, i, uid, broker_port))
    return trials


def run_one(trial: Trial):
    for attempt in range(3):          # a trial that fails to even connect is retried
        try:
            return trial, SCENARIOS[trial.scenario](trial), None
        except Exception:
            err = traceback.format_exc()
            time.sleep(1.0)
    return trial, None, err


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def write_csv(path, rows):
    if not rows:
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", nargs="*", default=list(SCENARIOS))
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--broker-port", type=int, default=1883)
    ap.add_argument("--nagle-broker-port", type=int, default=1885)
    a = ap.parse_args()

    needs_mqtt = any(s != "S0_nagle" for s in a.scenarios) or "S0_nagle" in a.scenarios
    if needs_mqtt and not port_open(a.broker_port):
        sys.exit(f"No MQTT broker on port {a.broker_port}. Start one (see docs/MQTT_SETUP.md).")
    if "S0_nagle" in a.scenarios and not port_open(a.nagle_broker_port):
        print(f"[warn] no broker on {a.nagle_broker_port}: skipping S0_nagle")
        a.scenarios = [s for s in a.scenarios if s != "S0_nagle"]

    os.makedirs(RAW, exist_ok=True)
    os.makedirs(TRACES, exist_ok=True)
    trials = build_trials(a.scenarios, a.trials, a.broker_port, a.nagle_broker_port)
    print(f"{len(trials)} trials, {a.workers} workers, scenarios: {', '.join(a.scenarios)}", flush=True)

    rows, samples, failures = defaultdict(list), defaultdict(list), []
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(a.workers, maxtasksperchild=1) as pool:
        for k, (trial, out, err) in enumerate(pool.imap_unordered(run_one, trials), 1):
            if out is None:
                failures.append({"scenario": trial.scenario, "transport": trial.transport,
                                 "condition": trial.condition, "trial": trial.index, "error": err})
                print(f"  FAILED {trial.scenario} {trial.transport} {trial.condition} #{trial.index}")
                continue
            rows[trial.scenario].append(out["row"])
            samples[trial.scenario].extend(out.get("samples", []))
            if "trace" in out:
                name = f"{trial.scenario}__{trial.transport}__{trial.condition}.csv"
                write_csv(os.path.join(TRACES, name), out["trace"])
            if k % 20 == 0 or k == len(trials):
                print(f"  {k}/{len(trials)} done ({time.time() - t0:.0f} s)", flush=True)

    for sc, rs in rows.items():
        rs.sort(key=lambda r: (r["transport"], r["condition"], str(r.get("broker_nodelay", "")),
                               str(r.get("client_nodelay", "")), r["trial"]))
        write_csv(os.path.join(RAW, f"{sc}.csv"), rs)
    for sc, ss in samples.items():
        write_csv(os.path.join(RAW, f"{sc}_samples.csv"), ss)
    write_csv(os.path.join(RAW, "failures.csv"), failures)

    info_path = os.path.join(ROOT, "results", "run_info.json")
    info = {}
    if os.path.exists(info_path):
        with open(info_path) as fh:
            info = json.load(fh)
    for sc in rows:
        info[sc] = {"finished": datetime.now().isoformat(timespec="seconds"),
                    "trials_per_cell": a.trials, "rows": len(rows[sc]),
                    "backend": "mock", "python": platform.python_version(),
                    "machine": f"{platform.system()} {platform.machine()}",
                    "workers": a.workers}
    info["conditions"] = {k: {"delay_ms": v.delay_ms, "jitter_ms": v.jitter_ms, "loss": v.loss}
                          for k, v in CONDITIONS.items()}
    with open(info_path, "w") as fh:
        json.dump(info, fh, indent=2)
    print(f"Done in {time.time() - t0:.0f} s. {sum(len(r) for r in rows.values())} trials OK, "
          f"{len(failures)} failed. CSVs in results/raw/", flush=True)


if __name__ == "__main__":
    main()
