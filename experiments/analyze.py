"""Turn results/raw/*.csv into summary tables (results/tables) and figures (results/figures).

    python experiments/analyze.py

Every figure carries a "backend: mock" note so no plot can be mistaken for a
CoppeliaSim result.
"""

from __future__ import annotations

import csv
import glob
import json
import math
import os
import statistics as st
import sys
from collections import defaultdict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from experiments.scenarios import LANE, SQUARE  # noqa: E402

RAW = os.path.join(ROOT, "results", "raw")
TRACES = os.path.join(ROOT, "results", "traces")
FIG = os.path.join(ROOT, "results", "figures")
TAB = os.path.join(ROOT, "results", "tables")

# Validated categorical slots 1-3 (light mode) - one colour per transport, fixed order.
COL = {"tcp": "#2a78d6", "mqtt_q0": "#eb6834", "mqtt_q1": "#1baf7a"}
NAME = {"tcp": "TCP socket", "mqtt_q0": "MQTT QoS 0", "mqtt_q1": "MQTT QoS 1"}
TRANSPORTS = ["tcp", "mqtt_q0", "mqtt_q1"]
CONDS = ["C0_ideal", "C1_50ms", "C2_100ms_1pct", "C3_200ms_5pct"]
CLABEL = {"C0_ideal": "C0: none", "C1_50ms": "C1: 50±10 ms",
          "C2_100ms_1pct": "C2: 100±25 ms, 1%", "C3_200ms_5pct": "C3: 200±50 ms, 5%"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Liberation Serif", "DejaVu Serif"],
    "font.size": 10, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
    "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "figure.dpi": 150, "savefig.dpi": 200, "savefig.bbox": "tight",
})


def load(name):
    path = os.path.join(RAW, name + ".csv")
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k, v in r.items():
            if v in ("", "None"):
                r[k] = None
            elif v in ("True", "False"):
                r[k] = v == "True"
            else:
                try:
                    r[k] = float(v)
                except (TypeError, ValueError):
                    pass
    return rows


def load_trace(name):
    path = os.path.join(TRACES, name + ".csv")
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [{k: (float(v) if k not in ("state", "mode") else v) for k, v in r.items()}
                for r in csv.DictReader(fh)]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else float("nan")


def sd(xs):
    xs = [x for x in xs if x is not None]
    return st.stdev(xs) if len(xs) > 1 else 0.0


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def note(fig, text="backend: mock (pure-Python simulator)"):
    # a right-aligned axis title never collides with tick labels or legends below it
    fig.axes[-1].set_title(text, loc="right", fontsize=7, color=INK2, style="italic")


def save(fig, name):
    os.makedirs(FIG, exist_ok=True)
    fig.savefig(os.path.join(FIG, name))
    plt.close(fig)


def write_table(name, header, rows):
    os.makedirs(TAB, exist_ok=True)
    with open(os.path.join(TAB, name + ".csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    with open(os.path.join(TAB, name + ".md"), "w") as fh:
        fh.write("| " + " | ".join(header) + " |\n|" + "---|" * len(header) + "\n")
        for r in rows:
            fh.write("| " + " | ".join(str(c) for c in r) + " |\n")


def by(rows, *keys):
    out = defaultdict(list)
    for r in rows:
        out[tuple(r[k] for k in keys)].append(r)
    return out


def legend_handles(ax):
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=COL[t], label=NAME[t]) for t in TRANSPORTS],
              loc="upper left", ncol=3, fontsize=8)


# ============================================================== S1 latency
def s1(summary):
    rows, samples = load("S1_latency"), load("S1_latency_samples")
    if not rows:
        return
    g, gs = by(rows, "transport", "condition"), by(samples, "transport", "condition")
    table = []
    for c in CONDS:
        for t in TRANSPORTS:
            rs = g[(t, c)]
            ms = [s["rtt_ms"] for s in gs[(t, c)]]
            got = [m for m in ms if m is not None]
            table.append([NAME[t], CLABEL[c], len(rs), f"{len(got)}/{len(ms)}",
                          f"{st.median(got):.1f}", f"{mean(got):.1f}", f"{pct(got, .95):.1f}",
                          f"{max(got):.1f}", f"{mean([r['up_Bps'] for r in rs]):.0f}",
                          f"{mean([r['down_Bps'] for r in rs]):.0f}"])
            summary[f"S1|{t}|{c}"] = {"median": st.median(got), "p95": pct(got, .95),
                                      "mean": mean(got), "max": max(got), "n": len(got),
                                      "up": mean([r['up_Bps'] for r in rs]),
                                      "down": mean([r['down_Bps'] for r in rs])}
    write_table("T_latency", ["Transport", "Condition", "Trials", "Replies", "Median RTT (ms)",
                              "Mean (ms)", "P95 (ms)", "Max (ms)", "Up (B/s)", "Down (B/s)"], table)

    # box plot of every ping
    fig, ax = plt.subplots(figsize=(6.4, 3.4))
    w = 0.24
    for j, t in enumerate(TRANSPORTS):
        data = [[s["rtt_ms"] for s in gs[(t, c)] if s["rtt_ms"] is not None] for c in CONDS]
        pos = [i + (j - 1) * (w + 0.03) for i in range(len(CONDS))]
        bp = ax.boxplot(data, positions=pos, widths=w, patch_artist=True, showfliers=True,
                        flierprops=dict(marker="o", markersize=2.5, markerfacecolor=COL[t],
                                        markeredgecolor="none", alpha=0.5),
                        medianprops=dict(color=INK, linewidth=1.2),
                        whiskerprops=dict(color=INK2), capprops=dict(color=INK2))
        for b in bp["boxes"]:
            b.set(facecolor=COL[t], edgecolor="white", linewidth=1.0)
    ax.set_yscale("log")
    ax.set_xticks(range(len(CONDS)), [CLABEL[c] for c in CONDS], fontsize=8.5)
    ax.set_ylabel("Ping round-trip time (ms, log scale)")
    legend_handles(ax)
    ax.set_ylim(0.3, 8000)
    note(fig, "backend: mock | 10 trials x 50 pings per box")
    save(fig, "fig_rtt_box.png")

    # CDF for the two impaired conditions with loss
    fig, axes = plt.subplots(1, 2, figsize=(6.4, 2.8), sharey=True)
    for ax, c in zip(axes, ["C2_100ms_1pct", "C3_200ms_5pct"]):
        for t in TRANSPORTS:
            xs = sorted(s["rtt_ms"] for s in gs[(t, c)] if s["rtt_ms"] is not None)
            ys = [(i + 1) / len(xs) for i in range(len(xs))]
            ax.plot(xs, ys, color=COL[t], linewidth=2, label=NAME[t])
        ax.set_xscale("log")
        ticks = [100, 200, 500, 1000, 2000] if c != "C2_100ms_1pct" else [100, 200, 300, 500, 800]
        ax.set_xticks(ticks, [str(x) for x in ticks])
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        ax.set_title(CLABEL[c], fontsize=9.5)
        ax.set_xlabel("RTT (ms, log)")
    axes[0].set_ylabel("Fraction of pings")
    axes[0].legend(fontsize=8, loc="lower right")
    note(fig)
    save(fig, "fig_rtt_cdf.png")


# ============================================================== S0 Nagle
def s0(summary):
    rows = load("S0_nagle")
    if not rows:
        return
    g = by(rows, "broker_nodelay", "client_nodelay")
    combos = [(False, False), (False, True), (True, False), (True, True)]
    labels = ["broker off\nclient off\n(defaults)", "broker off\nclient on", "broker on\nclient off",
              "broker on\nclient on\n(this project)"]
    table, med = [], []
    for (b, c), lab in zip(combos, labels):
        rs = g[(b, c)]
        m = [r["rtt_median_ms"] for r in rs]
        med.append((mean(m), sd(m)))
        table.append(["on" if b else "off (default)", "on" if c else "off (paho default)", len(rs),
                      f"{mean(m):.1f} ± {sd(m):.1f}", f"{mean([r['rtt_max_ms'] for r in rs]):.1f}"])
        summary[f"S0|{b}|{c}"] = {"median": mean(m), "sd": sd(m)}
    write_table("T_nagle", ["Broker TCP_NODELAY", "Client TCP_NODELAY", "Trials",
                            "Median RTT (ms, mean ± sd)", "Mean of max RTT (ms)"], table)
    fig, ax = plt.subplots(figsize=(5.6, 2.9))
    ax.bar(range(4), [m for m, _ in med], yerr=[s for _, s in med], width=0.55,
           color=COL["mqtt_q1"], edgecolor="white", linewidth=2, capsize=3, ecolor=INK2)
    for i, (m, _) in enumerate(med):
        ax.text(i, m + 2, f"{m:.1f} ms", ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(range(4), labels, fontsize=8)
    ax.set_ylabel("Median ping RTT (ms)")
    note(fig, "backend: mock | MQTT QoS 1, localhost, no impairment | 10 trials x 30 pings per bar")
    save(fig, "fig_nagle.png")


# ============================================================== S2 square
def s2(summary):
    rows = load("S2_square")
    if not rows:
        return
    g = by(rows, "transport", "condition")
    table = []
    fig, ax = plt.subplots(figsize=(6.4, 3.0))
    w = 0.26
    for j, t in enumerate(TRANSPORTS):
        means, sds = [], []
        for c in CONDS:
            rs = g[(t, c)]
            ct = [r["completion_s"] for r in rs]
            reached = sum(r["goals_reached"] for r in rs)
            means.append(mean(ct))
            sds.append(sd(ct))
            table.append([NAME[t], CLABEL[c], len(rs), f"{mean(ct):.2f} ± {sd(ct):.2f}",
                          f"{int(reached)}/{4 * len(rs)}",
                          f"{int(sum(r['reached_first_try'] for r in rs))}/{4 * len(rs)}",
                          int(sum(r["retries"] for r in rs)),
                          f"{mean([r['mean_goal_error_m'] for r in rs]) * 100:.1f}",
                          f"{mean([r['path_length_m'] for r in rs]):.2f}",
                          int(sum(r["link_lost"] for r in rs)), int(sum(r["collisions"] for r in rs))])
            summary[f"S2|{t}|{c}"] = {"time": mean(ct), "sd": sd(ct), "reached": reached,
                                      "first": sum(r['reached_first_try'] for r in rs),
                                      "retries": sum(r["retries"] for r in rs),
                                      "max_time": max(ct),
                                      "goals": 4 * len(rs),
                                      "link_lost": sum(r["link_lost"] for r in rs)}
        pos = [i + (j - 1) * (w + 0.02) for i in range(len(CONDS))]
        ax.bar(pos, means, w, yerr=sds, color=COL[t], edgecolor="white", linewidth=1.5,
               capsize=2, ecolor=INK2)
    ax.set_xticks(range(len(CONDS)), [CLABEL[c] for c in CONDS], fontsize=8.5)
    ax.set_ylabel("Time for the 4-goal square (s)")
    ax.set_ylim(20, None)
    legend_handles(ax)
    note(fig, "backend: mock | mean ± sd of 10 trials")
    save(fig, "fig_square_time.png")
    write_table("T_square", ["Transport", "Condition", "Trials", "Completion (s)", "Goals reached",
                             "First try", "Re-sent goals", "Mean goal error (cm)", "Path (m)", "Watchdog trips", "Collisions"], table)


# ============================================================== S3 operator
def s3(summary):
    rows = load("S3_operator")
    if not rows:
        return
    g = by(rows, "transport", "condition")
    table = []
    fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.9))
    w = 0.26
    for j, t in enumerate(TRANSPORTS):
        xm, xs, tm, ts = [], [], [], []
        for c in CONDS:
            rs = g[(t, c)]
            fin = sum(bool(r["finished"]) for r in rs)
            x = [r["xte_rms_m"] * 100 for r in rs]
            tt = [r["completion_s"] for r in rs]
            xm.append(mean(x)); xs.append(sd(x)); tm.append(mean(tt)); ts.append(sd(tt))
            table.append([NAME[t], CLABEL[c], f"{fin}/{len(rs)}", f"{mean(tt):.1f} ± {sd(tt):.1f}",
                          f"{mean(x):.1f} ± {sd(x):.1f}",
                          f"{mean([r['xte_max_m'] for r in rs]) * 100:.1f}",
                          f"{mean([r['min_clearance_m'] for r in rs]):.2f}",
                          int(sum(r["stale_rejected"] for r in rs)), int(sum(r["link_lost"] for r in rs)),
                          int(sum(r["collisions"] for r in rs))])
            summary[f"S3|{t}|{c}"] = {"finished": fin, "n": len(rs), "time": mean(tt),
                                      "xte": mean(x), "xte_sd": sd(x),
                                      "stale": sum(r["stale_rejected"] for r in rs),
                                      "link_lost": sum(r["link_lost"] for r in rs)}
        pos = [i + (j - 1) * (w + 0.02) for i in range(len(CONDS))]
        axes[0].bar(pos, xm, w, yerr=xs, color=COL[t], edgecolor="white", linewidth=1.5, capsize=2, ecolor=INK2)
        axes[1].bar(pos, tm, w, yerr=ts, color=COL[t], edgecolor="white", linewidth=1.5, capsize=2,
                    ecolor=INK2, label=NAME[t])
    short = ["C0", "C1", "C2", "C3"]
    axes[0].set_xticks(range(4), short); axes[1].set_xticks(range(4), short)
    axes[0].set_ylabel("RMS cross-track error (cm)")
    axes[1].set_ylabel("Completion time (s)")
    axes[1].axhline(60, color=INK2, linestyle="--", linewidth=1)
    axes[1].text(-0.4, 61, "60 s time limit", fontsize=7.5, color=INK2)
    axes[1].set_ylim(0, 75)
    fig.legend(*axes[1].get_legend_handles_labels(), loc="upper center", ncol=3, fontsize=8,
               bbox_to_anchor=(0.5, 1.06))
    note(fig, "backend: mock | synthetic operator model | mean ± sd of 10 trials")
    save(fig, "fig_operator_bars.png")
    write_table("T_operator", ["Transport", "Condition", "Finished", "Time (s)", "RMS XTE (cm)",
                               "Max XTE (cm)", "Min clearance (m)", "Stale rejected",
                               "Watchdog trips", "Collisions"], table)

    # trajectories, TCP trial 0 per condition
    fig, ax = plt.subplots(figsize=(4.6, 4.0))
    lx, ly = zip(*LANE)
    ax.plot(lx, ly, color=INK2, linewidth=6, alpha=0.18, solid_capstyle="round", label="reference lane")
    seq = ["#9ec5f4", "#5b9ae6", "#2a78d6", "#0f3f80"]   # one hue, light -> dark = harsher link
    for c, colr in zip(CONDS, seq):
        tr = load_trace(f"S3_operator__tcp__{c}")
        if tr:
            ax.plot([r["x"] for r in tr], [r["y"] for r in tr], color=colr, linewidth=1.6, label=CLABEL[c])
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    ax.legend(fontsize=7.5, loc="center", bbox_to_anchor=(0.5, 0.5))
    note(fig, "backend: mock | TCP, trial 0 of each condition")
    save(fig, "fig_operator_paths.png")


# ============================================================== S4 outage
def s4(summary):
    rows = load("S4_outage")
    if not rows:
        return
    g = by(rows, "transport")
    table = []
    for t in TRANSPORTS:
        rs = g[(t,)]
        n_during = sum(r["cmds_during"] for r in rs)
        table.append([NAME[t], len(rs), f"{mean([r['watchdog_stop_s'] for r in rs]):.2f} ± "
                      f"{sd([r['watchdog_stop_s'] for r in rs]):.2f}",
                      f"{mean([r['coast_dist_m'] for r in rs]) * 100:.1f}",
                      int(n_during), int(sum(r["cmds_lost"] for r in rs)),
                      int(sum(r["cmds_rejected_stale"] for r in rs)),
                      int(sum(r["cmds_executed_late"] for r in rs)),
                      f"{int(sum(r['pings_answered_late'] for r in rs))}/{int(sum(r['pings_during'] for r in rs))}",
                      f"{mean([r['resume_after_s'] for r in rs]):.2f}",
                      int(sum(r["collisions"] for r in rs))])
        summary[f"S4|{t}"] = {"stop": mean([r['watchdog_stop_s'] for r in rs]),
                              "coast": mean([r['coast_dist_m'] for r in rs]),
                              "during": n_during, "lost": sum(r["cmds_lost"] for r in rs),
                              "stale": sum(r["cmds_rejected_stale"] for r in rs),
                              "late": sum(r["cmds_executed_late"] for r in rs),
                              "pings_late": sum(r['pings_answered_late'] for r in rs),
                              "pings": sum(r['pings_during'] for r in rs),
                              "resume": mean([r['resume_after_s'] for r in rs])}
    write_table("T_outage", ["Transport", "Trials", "Stop after outage start (s)", "Coast (cm)",
                             "Cmds sent in outage", "Lost", "Rejected stale", "Executed late",
                             "Pings answered late", "Resume after link back (s)", "Collisions"], table)

    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    for t in TRANSPORTS:
        tr = load_trace(f"S4_outage__{t}__C1_50ms")
        if tr:
            ax.plot([r["t"] for r in tr], [r["v"] for r in tr], color=COL[t], linewidth=2, label=NAME[t])
    ax.axvspan(0, 3, color=GRID, alpha=0.6, linewidth=0)
    ax.axvline(1.0, color=INK2, linestyle=":", linewidth=1)
    ax.text(2.05, 0.13, "link down (3 s)", fontsize=8, color=INK2, ha="center")
    ax.text(1.05, 0.02, "watchdog 1 s", fontsize=7.5, color=INK2)
    ax.set_xlim(-2, 7)
    ax.set_xlabel("Time since outage start (s)")
    ax.set_ylabel("Robot speed v (m/s)")
    ax.legend(fontsize=8, loc="lower right")
    note(fig, "backend: mock | C1 link, trial 0 per transport")
    save(fig, "fig_outage_timeline.png")


# ============================================================== S5 safety
def s5(summary):
    rows = load("S5_safety")
    if not rows:
        return
    g = by(rows, "transport", "condition")
    table = []
    fig, ax = plt.subplots(figsize=(6.4, 2.8))
    w = 0.26
    for j, t in enumerate(TRANSPORTS):
        data = []
        for c in CONDS:
            rs = g[(t, c)]
            cl = [r["min_clearance_m"] * 100 for r in rs]
            data.append([x for x, r in zip(cl, rs) if r['time_to_stop_s'] is not None])
            reached_box = [r["min_clearance_m"] * 100 for r in rs if r["time_to_stop_s"] is not None]
            table.append([NAME[t], CLABEL[c], len(rs), f"{len(reached_box)}/{len(rs)}",
                          f"{mean(reached_box):.1f}", f"{min(cl):.1f}",
                          int(sum(r["link_lost"] for r in rs)), int(sum(r["collisions"] for r in rs))])
            summary[f"S5|{t}|{c}"] = {"mean": mean(reached_box), "min": min(cl),
                                      "stopped_at_box": len(reached_box),
                                      "link_lost": sum(r["link_lost"] for r in rs),
                                      "coll": sum(r["collisions"] for r in rs)}
        pos = [i + (j - 1) * (w + 0.03) for i in range(len(CONDS))]
        for p, d in zip(pos, data):
            ax.scatter([p] * len(d), d, s=14, color=COL[t], edgecolor="white", linewidth=0.5, zorder=3)
    ax.axhline(30, color=INK2, linestyle="--", linewidth=1)
    ax.text(3.45, 30.05, "stop distance 30 cm", fontsize=7.5, color=INK2, ha="right", va="bottom")
    ax.set_ylim(27, 31)   # trials stopped early by the watchdog sit above this range (see table)
    ax.set_xticks(range(4), [CLABEL[c] for c in CONDS], fontsize=8.5)
    ax.set_ylabel("Closest approach to box (cm)")
    legend_handles(ax)
    note(fig, "backend: mock | 10 trials per transport and condition")
    save(fig, "fig_safety.png")
    write_table("T_safety", ["Transport", "Condition", "Trials", "Stopped by obstacle guard",
                             "Mean clearance at stop (cm)", "Worst clearance (cm)",
                             "Watchdog trips", "Collisions"], table)


# ============================================================== PID tuning
def pid(summary):
    rows = load("pid_tuning")
    if not rows:
        return
    g = by(rows, "gain_set")
    table = []
    for name, rs in g.items():
        stt = [r["settling_s"] for r in rs]
        table.append([name[0], len(rs), f"{mean([r['overshoot_deg'] for r in rs]):.2f}",
                      f"{max(r['overshoot_deg'] for r in rs):.2f}", f"{mean(stt):.2f}",
                      f"{mean([r['final_error_deg'] for r in rs]):.2f}",
                      f"{sum(r['outcome'] == 'reached' for r in rs)}/{len(rs)}"])
        summary[f"PID|{name[0]}"] = {"overshoot": mean([r['overshoot_deg'] for r in rs]),
                                     "settle": mean(stt),
                                     "reached": sum(r['outcome'] == 'reached' for r in rs)}
    write_table("T_pid", ["Gain set", "Turns", "Mean overshoot (deg)", "Max overshoot (deg)",
                          "Mean settling time to ±2 deg (s)", "Mean final error (deg)", "Reached"], table)
    fig, ax = plt.subplots(figsize=(6.0, 3.0))
    files = sorted(glob.glob(os.path.join(TRACES, "pid_step_*.csv")))
    palette = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
    order = ["P_Kp_1_0", "P_Kp_3_0", "P_Kp_8_0", "PD_Kp_3_0_Kd_0_15", "PID_Kp_3_Ki_1_Kd_0_15"]
    labels = ["P, Kp=1", "P, Kp=3", "P, Kp=8", "PD, Kp=3 Kd=0.15 (used in runs)", "PID, Kp=3 Ki=1 Kd=0.15"]
    for key, colr, lab in zip(order, palette, labels):
        tr = load_trace("pid_step_" + key)
        if tr:
            ax.plot([r["t"] for r in tr], [r["heading_deg"] for r in tr], color=colr, linewidth=1.8, label=lab)
    ax.axhline(90, color=INK2, linestyle="--", linewidth=1)
    ax.set_xlim(0, 6)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Heading (deg)")
    ax.legend(fontsize=7.5, loc="lower right")
    note(fig, "backend: mock | 'turn 90' step response")
    save(fig, "fig_pid_step.png")


# ============================================================== square path figure
def square_paths():
    fig, ax = plt.subplots(figsize=(4.0, 3.6))
    sx, sy = zip(*([(0.0, 0.0)] + SQUARE))
    ax.plot(sx, sy, color=INK2, linewidth=6, alpha=0.18, solid_capstyle="round", label="goal sequence")
    for c, colr, lw in zip(["C0_ideal", "C3_200ms_5pct"], ["#9ec5f4", "#0f3f80"], [4.5, 1.4]):
        tr = load_trace(f"S2_square__tcp__{c}")
        if tr:
            ax.plot([r["x"] for r in tr], [r["y"] for r in tr], color=colr, linewidth=lw, label=CLABEL[c])
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    ax.legend(fontsize=7.5, loc="center")
    note(fig, "backend: mock | TCP, trial 0")
    save(fig, "fig_square_paths.png")


def main():
    summary = {}
    for fn in (s0, s1, s2, s3, s4, s5, pid):
        fn(summary)
    square_paths()
    with open(os.path.join(ROOT, "results", "summary.json"), "w") as fh:
        json.dump(summary, fh, indent=1, default=float)
    print("tables:", sorted(os.listdir(TAB)) if os.path.isdir(TAB) else [])
    print("figures:", sorted(os.listdir(FIG)) if os.path.isdir(FIG) else [])


if __name__ == "__main__":
    main()
