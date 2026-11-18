"""One function per experiment scenario.  Each runs ONE trial and returns a
dict of metrics (plus optional per-sample rows and a trace).

Every trial builds its own private system:

    OperatorClient --TCP--> ImpairmentProxy --TCP--> RobotServer (tcp)
                                            \\--TCP--> Mosquitto --> RobotServer (mqtt)

so trials can run in parallel processes without disturbing each other
(separate ports, separate MQTT topics "teleop/exp<id>/...").

All numbers come from the mock backend (backend name is stored in every row).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from teleop.backends import MockBackend
from teleop.client import OperatorClient
from teleop.config import ServerParams
from teleop.netem import Impairment, ImpairmentProxy
from teleop.server import RobotServer
from teleop.transport.mqtt import MqttClient, MqttServer
from teleop.transport.tcp import TcpClient, TcpServer

# --------------------------------------------------------------------------- matrix
CONDITIONS: Dict[str, Impairment] = {
    "C0_ideal":       Impairment(0, 0, 0.0),
    "C1_50ms":        Impairment(50, 10, 0.0),
    "C2_100ms_1pct":  Impairment(100, 25, 0.01),
    "C3_200ms_5pct":  Impairment(200, 50, 0.05),
}
TRANSPORTS = ["tcp", "mqtt_q0", "mqtt_q1"]

SQUARE = [(2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (0.0, 0.0)]
LANE = [(0.0, 0.0), (2.5, 0.0), (2.5, 2.5), (0.5, 2.5)]


@dataclass
class Trial:
    scenario: str
    transport: str
    condition: str
    index: int               # trial number within its cell (0..n-1)
    uid: int                 # globally unique id -> topic names, seeds
    broker_port: int = 1883
    extra: Optional[dict] = None


class System:
    """Server + proxy + client for one trial."""

    def __init__(self, t: Trial, start_pose=(0.0, 0.0, 0.0), mqtt_nodelay=True):
        self.t = t
        imp = CONDITIONS.get(t.condition, Impairment())
        self.params = ServerParams(record_trace=True)
        self.backend = MockBackend(self.params.robot, start_pose=start_pose, seed=t.uid)
        rid = f"exp{t.uid}"
        if t.transport == "tcp":
            st = TcpServer("127.0.0.1", 0)
        else:
            qos = int(t.transport[-1])
            st = MqttServer("127.0.0.1", t.broker_port, robot_id=rid, qos=qos, keepalive=2,
                            client_id=f"robot-{rid}", nodelay=mqtt_nodelay)
        self.server = RobotServer(self.backend, st, self.params)
        self.server.start()
        self.server.run_in_thread()
        target = st.port if t.transport == "tcp" else t.broker_port
        self.proxy = ImpairmentProxy(0, "127.0.0.1", target, imp, seed=t.uid).start()
        if t.transport == "tcp":
            ct = TcpClient("127.0.0.1", self.proxy.port, reconnect_interval=0.2)
        else:
            ct = MqttClient("127.0.0.1", self.proxy.port, robot_id=rid, qos=int(t.transport[-1]),
                            keepalive=2, client_id=f"operator-{rid}", nodelay=mqtt_nodelay)
        self.client = OperatorClient(ct)
        self.client.connect(timeout=15)
        time.sleep(0.5)              # let telemetry start flowing

    def close(self) -> None:
        for fn in (self.client.close, self.server.close, self.proxy.close):
            try:
                fn()
            except Exception:
                pass

    def base_row(self) -> dict:
        return {"scenario": self.t.scenario, "backend": self.backend.name,
                "transport": self.t.transport, "condition": self.t.condition,
                "trial": self.t.index}


# --------------------------------------------------------------------------- helpers
def path_length(trace) -> float:
    return sum(math.hypot(b[2] - a[2], b[3] - a[3]) for a, b in zip(trace, trace[1:]))


def dist_to_polyline(x: float, y: float, pts: List[Tuple[float, float]]) -> float:
    best = float("inf")
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        ex, ey = x2 - x1, y2 - y1
        L2 = ex * ex + ey * ey
        u = max(0.0, min(1.0, ((x - x1) * ex + (y - y1) * ey) / L2))
        best = min(best, math.hypot(x - x1 - u * ex, y - y1 - u * ey))
    return best


def trace_rows(trace, t0: float) -> List[dict]:
    return [{"t": round(r[0] - t0, 3), "x": round(r[2], 4), "y": round(r[3], 4),
             "theta": round(r[4], 4), "v": round(r[5], 3), "w": round(r[6], 3),
             "state": r[7], "mode": r[8], "front": round(r[9], 3)} for r in trace]


# --------------------------------------------------------------------------- S1 latency
def s1_latency(t: Trial) -> dict:
    """50 pings at 5 Hz.  Ping RTT = network round trip (answered in the server's IO thread)."""
    sysm = System(t)
    try:
        rtts: List[Optional[float]] = []
        b0 = dict(sysm.proxy.bytes)
        t_start = time.monotonic()
        for i in range(50):
            t_next = t_start + 0.2 * (i + 1)
            rtts.append(sysm.client.ping(timeout=5.0))
            delay = t_next - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        elapsed = time.monotonic() - t_start
        got = [r for r in rtts if r is not None]
        row = sysm.base_row()
        ms = sorted(r * 1000 for r in got)
        row.update({
            "pings": len(rtts), "replies": len(got),
            "rtt_mean_ms": sum(ms) / len(ms) if ms else None,
            "rtt_median_ms": ms[len(ms) // 2] if ms else None,
            "rtt_p95_ms": ms[min(len(ms) - 1, int(0.95 * len(ms)))] if ms else None,
            "rtt_max_ms": ms[-1] if ms else None,
            "up_Bps": (sysm.proxy.bytes["up"] - b0["up"]) / elapsed,
            "down_Bps": (sysm.proxy.bytes["down"] - b0["down"]) / elapsed,
            "retransmissions": sysm.proxy.retransmissions,
            "duplicates": sysm.client.duplicates,
        })
        samples = [{"transport": t.transport, "condition": t.condition, "trial": t.index,
                    "i": i, "rtt_ms": None if r is None else round(r * 1000, 3)}
                   for i, r in enumerate(rtts)]
        return {"row": row, "samples": samples}
    finally:
        sysm.close()


# --------------------------------------------------------------------------- S2 goto square
def s2_square(t: Trial) -> dict:
    """Supervisory control: four goto commands around a 2 m square.

    The operator behaves like a person at a terminal: if a goal is rejected
    (stale) or aborted by the watchdog (link_lost), they type it again - up
    to 3 retries per goal.  Retries are counted."""
    sysm = System(t)
    try:
        c = sysm.client
        t0 = time.monotonic()
        outcomes, errors, retries, first_try = [], [], 0, 0
        for (x, y) in SQUARE:
            for attempt in range(4):
                p = c.send_command("goto", {"x": x, "y": y, "speed": 0.4})
                if not c.wait_ack(p, 10) or not p.ok:
                    outcome = "rejected" if p.ack is not None else "no_ack"
                    err = None
                elif c.wait_result(p, 60):
                    outcome, err = p.result["outcome"], p.result["error"]
                else:
                    outcome, err = "no_result", None
                if outcome == "reached" or outcome not in ("rejected", "no_ack", "link_lost"):
                    break
                retries += 1
            first_try += attempt == 0 and outcome == "reached"
            outcomes.append(outcome)
            errors.append(err)
        total = time.monotonic() - t0
        tr = sysm.server.trace
        row = sysm.base_row()
        good = [e for e in errors if e is not None]
        row.update({
            "completion_s": total,
            "goals_reached": sum(o == "reached" for o in outcomes),
            "reached_first_try": first_try,
            "retries": retries,
            "outcomes": "|".join(outcomes),
            "mean_goal_error_m": sum(good) / len(good) if good else None,
            "path_length_m": path_length(tr),
            "collisions": sysm.backend.collisions(),
            "link_lost": sysm.server.stats["link_lost"],
            "stale_rejected": sysm.server.stats["stale"],
        })
        out = {"row": row}
        if t.index == 0:
            out["trace"] = trace_rows(tr, tr[0][0])
        return out
    finally:
        sysm.close()


# --------------------------------------------------------------------------- S3 operator in the loop
class OperatorModel:
    """A simple, repeatable stand-in for a human driver (NOT a human).

    Every 0.2 s it looks at the robot pose it last SAW (telemetry, which is
    already delayed by the network), adds a 0.2 s human reaction time, and
    steers with pure pursuit towards a point 0.5 m ahead on the lane, sending
    a `vel` command.  This is how a person drives with a joystick: they react
    to what the video/telemetry showed a moment ago.
    """

    def __init__(self, path, v=0.35, lookahead=0.5, reaction=0.2, period=0.2):
        self.path, self.v, self.L = path, v, lookahead
        self.reaction, self.period = reaction, period
        self.seen: List[Tuple[float, Tuple[float, float, float]]] = []

    def observe(self, now: float, pose) -> None:
        if not self.seen or self.seen[-1][1] != tuple(pose):
            self.seen.append((now, tuple(pose)))
        self.seen = self.seen[-200:]

    def perceived(self, now: float):
        """Latest pose the operator has had time to react to."""
        cand = [p for (ts, p) in self.seen if ts <= now - self.reaction]
        return cand[-1] if cand else None

    def lookahead_point(self, x, y):
        # nearest point on the lane, then walk L metres further along it
        best, best_i, best_u = float("inf"), 0, 0.0
        for i, ((x1, y1), (x2, y2)) in enumerate(zip(self.path, self.path[1:])):
            ex, ey = x2 - x1, y2 - y1
            L2 = ex * ex + ey * ey
            u = max(0.0, min(1.0, ((x - x1) * ex + (y - y1) * ey) / L2))
            d = math.hypot(x - x1 - u * ex, y - y1 - u * ey)
            if d < best:
                best, best_i, best_u = d, i, u
        remaining = self.L
        i, u = best_i, best_u
        while i < len(self.path) - 1:
            (x1, y1), (x2, y2) = self.path[i], self.path[i + 1]
            seg = math.hypot(x2 - x1, y2 - y1)
            left = (1 - u) * seg
            if remaining <= left:
                f = u + remaining / seg
                return x1 + f * (x2 - x1), y1 + f * (y2 - y1)
            remaining -= left
            i, u = i + 1, 0.0
        return self.path[-1]

    def command(self, pose):
        x, y, th = pose
        gx, gy = self.lookahead_point(x, y)
        alpha = math.atan2(gy - y, gx - x) - th
        alpha = (alpha + math.pi) % (2 * math.pi) - math.pi
        dist_goal = math.hypot(self.path[-1][0] - x, self.path[-1][1] - y)
        v = min(self.v, 0.8 * dist_goal + 0.05)
        if abs(alpha) > math.radians(60):     # pointing far away: turn on the spot first
            v = 0.0
        w = 2.0 * self.v * math.sin(alpha) / self.L
        return v, max(-90.0, min(90.0, math.degrees(w)))


def s3_operator(t: Trial) -> dict:
    sysm = System(t)
    try:
        c = sysm.client
        op = OperatorModel(LANE)
        t0 = time.monotonic()
        sent = 0
        finished = False
        while time.monotonic() - t0 < 60:
            now = time.monotonic()
            if c.telemetry:
                op.observe(now, c.telemetry["pose"])
            pose = op.perceived(now)
            if pose is not None:
                if math.hypot(pose[0] - LANE[-1][0], pose[1] - LANE[-1][1]) < 0.15:
                    finished = True
                    break
                v, w = op.command(pose)
                c.send_command("vel", {"v": round(v, 3), "w": round(w, 2)})
                sent += 1
            time.sleep(op.period)
        c.send_command("stop")
        t_done = time.monotonic() - t0
        time.sleep(0.5)
        tr = [r for r in sysm.server.trace if r[0] >= t0]
        xte = [dist_to_polyline(r[2], r[3], LANE) for r in tr]
        moving = [e for e, r in zip(xte, tr) if abs(r[5]) > 0.01 or abs(r[6]) > 0.01]
        clear = [sysm.backend.clearance(r[2], r[3]) for r in tr]
        row = sysm.base_row()
        row.update({
            "finished": finished, "completion_s": t_done,
            "xte_rms_m": math.sqrt(sum(e * e for e in moving) / len(moving)) if moving else None,
            "xte_max_m": max(moving) if moving else None,
            "path_length_m": path_length(tr),
            "min_clearance_m": min(clear) if clear else None,
            "commands_sent": sent,
            "obstacle_ticks": sum(r[7] == "OBSTACLE" for r in tr),
            "stale_rejected": sysm.server.stats["stale"],
            "link_lost": sysm.server.stats["link_lost"],
            "collisions": sysm.backend.collisions(),
        })
        out = {"row": row}
        if t.index == 0:
            out["trace"] = trace_rows(tr, t0)
        return out
    finally:
        sysm.close()


# --------------------------------------------------------------------------- S4 link outage
def s4_outage(t: Trial) -> dict:
    """Operator holds 'vel 0.25 0' (re-sent at 5 Hz) and pings every 0.5 s.
    At t = 2 s the link goes down for 3 s, then comes back (connections reset)."""
    outage_len = (t.extra or {}).get("outage_s", 3.0)
    sysm = System(t)
    try:
        c = sysm.client
        srv = sysm.server
        t0 = time.monotonic()
        t_out, t_back = t0 + 2.0, t0 + 2.0 + outage_len
        outage_started = False
        during_cmds, during_pings = [], []
        next_ping = t0
        while time.monotonic() - t0 < 2.0 + outage_len + 4.0:
            now = time.monotonic()
            if not outage_started and now >= t_out:
                sysm.proxy.outage(outage_len)
                outage_started = True
            p = c.send_command("vel", {"v": 0.25, "w": 0.0})
            if t_out <= now < t_back:
                during_cmds.append(p)
            if now >= next_ping:
                pp = c.send_command("ping")
                if t_out <= now < t_back:
                    during_pings.append(pp)
                next_ping = now + 0.5
            time.sleep(0.2)
        c.send_command("stop")
        time.sleep(1.0)
        tr = srv.trace
        # When did the robot stop after the outage began?
        stop_t, x_out = None, None
        for r in tr:
            if r[0] >= t_out:
                if x_out is None:
                    x_out = (r[2], r[3])
                if abs(r[5]) < 1e-3 and r[7] == "LINK_LOST":
                    stop_t = r
                    break
        resume = next((r for r in tr if r[0] >= t_back and r[5] > 0.05), None)
        during_seqs = {p.seq for p in during_cmds}
        started = [e for e in srv.events if e[1] == "start" and e[2] in during_seqs]
        stale = [e for e in srv.events if e[1] == "stale" and e[2] in during_seqs]
        row = sysm.base_row()
        row.update({
            "outage_s": outage_len,
            "watchdog_stop_s": None if stop_t is None else stop_t[0] - t_out,
            "coast_dist_m": None if stop_t is None or x_out is None else
            math.hypot(stop_t[2] - x_out[0], stop_t[3] - x_out[1]),
            "resume_after_s": None if resume is None else resume[0] - t_back,
            "cmds_during": len(during_cmds),
            "cmds_refused_by_client": sum(not p.sent for p in during_cmds),
            "cmds_executed_late": len(started),
            "cmds_rejected_stale": len(stale),
            "cmds_lost": len(during_cmds) - len(started) - len(stale),
            "pings_during": len(during_pings),
            "pings_answered_late": sum(p.ack is not None for p in during_pings),
            "link_lost_events": srv.stats["link_lost"],
            "client_reconnects": max(0, c.transport.reconnects),
            "collisions": sysm.backend.collisions(),
        })
        out = {"row": row}
        if t.index == 0:
            out["trace"] = trace_rows(tr, t_out)
        return out
    finally:
        sysm.close()


# --------------------------------------------------------------------------- S5 obstacle safety
def s5_safety(t: Trial) -> dict:
    """Operator drives straight at the box (vel 0.5) and never sends stop.
    Only the on-robot safety layer can prevent the collision."""
    sysm = System(t)
    try:
        c = sysm.client
        t0 = time.monotonic()
        c.send_command("vel", {"v": 0.5, "w": 0.0})
        time.sleep(10.0)
        tr = [r for r in sysm.server.trace if r[0] >= t0]
        clear = [sysm.backend.clearance(r[2], r[3]) for r in tr]
        stop_r = next((r for r in tr if r[7] == "OBSTACLE"), None)
        row = sysm.base_row()
        row.update({
            "min_clearance_m": min(clear),
            "final_x_m": tr[-1][2],
            "time_to_stop_s": None if stop_r is None else stop_r[0] - t0,
            "collisions": sysm.backend.collisions(),
            "link_lost": sysm.server.stats["link_lost"],
            "peak_v": max(r[5] for r in tr),
        })
        return {"row": row}
    finally:
        sysm.close()


# --------------------------------------------------------------------------- S0 Nagle ablation
def s0_nagle(t: Trial) -> dict:
    """MQTT QoS 1, no impairment: TCP_NODELAY on/off on client side and broker side."""
    ex = t.extra or {}
    sysm = System(t, mqtt_nodelay=ex["client_nodelay"])
    try:
        time.sleep(0.2)
        rtts = [sysm.client.ping(timeout=2.0) for _ in range(30)]
        ms = sorted(r * 1000 for r in rtts if r is not None)
        row = sysm.base_row()
        row.update({"broker_nodelay": ex["broker_nodelay"], "client_nodelay": ex["client_nodelay"],
                    "replies": len(ms), "rtt_median_ms": ms[len(ms) // 2],
                    "rtt_mean_ms": sum(ms) / len(ms), "rtt_max_ms": ms[-1]})
        return {"row": row}
    finally:
        sysm.close()


SCENARIOS = {"S0_nagle": s0_nagle, "S1_latency": s1_latency, "S2_square": s2_square,
             "S3_operator": s3_operator, "S4_outage": s4_outage, "S5_safety": s5_safety}
