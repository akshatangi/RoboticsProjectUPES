"""Heading-PID tuning study (no network, mock backend, simulated time).

For each gain set we run 10 `turn` commands with different target angles
(30..165 deg) and measure overshoot, settling time and final error.  Also
records one 90-degree step-response trace per gain set for the report figure.

    python experiments/pid_tuning.py      -> results/raw/pid_tuning.csv, results/traces/pid_step_*.csv
"""

from __future__ import annotations

import csv
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from teleop.backends import MockBackend, World  # noqa: E402
from teleop.config import ControlGains, RobotParams  # noqa: E402
from teleop.controller import MotionController  # noqa: E402
from teleop.kinematics import rate_limit, saturate_wheels, unicycle_to_wheels, wrap_angle  # noqa: E402

DT = 0.05
GAIN_SETS = {
    "P Kp=1.0":            dict(heading_kp=1.0, heading_ki=0.0, heading_kd=0.0),
    "P Kp=3.0":            dict(heading_kp=3.0, heading_ki=0.0, heading_kd=0.0),
    "P Kp=8.0":            dict(heading_kp=8.0, heading_ki=0.0, heading_kd=0.0),
    "PD Kp=3.0 Kd=0.15":   dict(heading_kp=3.0, heading_ki=0.0, heading_kd=0.15),
    "PID Kp=3 Ki=1 Kd=0.15": dict(heading_kp=3.0, heading_ki=1.0, heading_kd=0.15),
}
ANGLES = [30, 45, 60, 75, 90, 105, 120, 135, 150, 165]   # 180 is ambiguous (either way round)
BAND_DEG = 2.0     # settling band


def run_turn(gains: ControlGains, angle_deg: float, record=False):
    rp = RobotParams()
    robot = MockBackend(rp, World(), sonar_noise=0.0)
    ctrl = MotionController(rp, gains)
    # Fast turn (rate cap 120 deg/s) so the gains, not the rate cap, shape the response.
    ctrl.start(1, "turn", {"angle": angle_deg, "rate": 120.0}, robot.get_pose())
    target = math.radians(angle_deg)
    w_prev = 0.0
    rows, peak, t, res, settle_t = [], -1e9, 0.0, None, None
    while t < 15.0:
        v, w, r = ctrl.step(robot.get_pose(), DT)
        res = res or r
        w = rate_limit(w, w_prev, rp.max_ang_accel, DT)      # same ramp as the server
        w_prev = w
        wl, wr = saturate_wheels(*unicycle_to_wheels(0.0, w, rp.wheel_radius, rp.wheel_base),
                                 rp.max_wheel_speed)
        robot.set_wheel_speeds(wl, wr)
        robot.step(DT)
        t += DT
        heading = robot.get_pose()[2]
        rel = target + wrap_angle(heading - target)          # unwrapped around the target
        peak = max(peak, rel)
        err = abs(math.degrees(wrap_angle(heading - target)))
        if err <= BAND_DEG:
            settle_t = settle_t if settle_t is not None else t
        else:
            settle_t = None
        if record:
            rows.append({"t": round(t, 3), "heading_deg": round(math.degrees(rel), 3),
                         "target_deg": angle_deg})
        if res is not None and t > res.duration + 1.0:
            break
    return {"overshoot_deg": max(0.0, math.degrees(peak - target)),
            "settling_s": settle_t,
            "final_error_deg": abs(math.degrees(wrap_angle(robot.get_pose()[2] - target))),
            "outcome": res.outcome if res else "none",
            "duration_s": res.duration if res else None}, rows


def main():
    out_dir = os.path.join(ROOT, "results", "raw")
    tr_dir = os.path.join(ROOT, "results", "traces")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(tr_dir, exist_ok=True)
    rows = []
    for name, g in GAIN_SETS.items():
        for i, ang in enumerate(ANGLES):
            m, trace = run_turn(ControlGains(**g), ang, record=(ang == 90))
            rows.append({"backend": "mock", "gain_set": name, "trial": i, "angle_deg": ang, **m})
            if trace:
                safe = "".join(ch if ch.isalnum() else "_" for ch in name)
                with open(os.path.join(tr_dir, f"pid_step_{safe}.csv"), "w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=list(trace[0]))
                    w.writeheader()
                    w.writerows(trace)
    with open(os.path.join(out_dir, "pid_tuning.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for name in GAIN_SETS:
        sel = [r for r in rows if r["gain_set"] == name]
        st = [r["settling_s"] for r in sel if r["settling_s"] is not None]
        print(f"{name:24s} overshoot mean {sum(r['overshoot_deg'] for r in sel) / len(sel):5.2f} deg "
              f"(max {max(r['overshoot_deg'] for r in sel):5.2f})  settling mean "
              f"{(sum(st) / len(st)) if st else float('nan'):5.2f} s  final err mean "
              f"{sum(r['final_error_deg'] for r in sel) / len(sel):4.2f} deg  reached "
              f"{sum(r['outcome'] == 'reached' for r in sel)}/{len(sel)}")


if __name__ == "__main__":
    main()
