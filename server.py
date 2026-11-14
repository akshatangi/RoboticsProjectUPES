"""Robot-side server: network -> commands -> controller -> safety -> robot.

One loop runs at a fixed rate (20 Hz).  Every tick it:

  1. takes all commands that arrived since the last tick (they are put in a
     queue by the transport's background thread) and acknowledges them;
  2. checks the link watchdog;
  3. reads pose and sonars from the backend;
  4. asks the motion controller for (v, omega);
  5. passes them through the safety layer (obstacle stop / slow-down);
  6. limits acceleration and converts to wheel speeds;
  7. steps the backend (mock physics or one CoppeliaSim step);
  8. sends telemetry (every second tick = 10 Hz) and any finished result.

`ping` is answered straight from the network thread, so ping round-trip time
measures the network only, not the 50 ms tick.

Run it:   python -m teleop.server --backend mock --transport tcp --port 9000
"""

from __future__ import annotations

import argparse
import logging
import queue
import signal
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from .backends import RobotBackend, make_backend
from .config import ServerParams
from .controller import MotionController, Result
from .kinematics import rate_limit, saturate_wheels, unicycle_to_wheels
from .protocol import GOAL_COMMANDS, MOTION_COMMANDS, ProtocolError, validate_cmd
from .safety import SafetyLayer, front_distance
from .transport import ServerTransport, make_server

log = logging.getLogger("teleop.server")


class RobotServer:
    def __init__(self, backend: RobotBackend, transport: ServerTransport,
                 params: Optional[ServerParams] = None):
        self.backend = backend
        self.transport = transport
        self.p = params or ServerParams()
        self.controller = MotionController(self.p.robot, self.p.gains)
        self.safety = SafetyLayer(self.p.safety)
        self.inbox: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self.last_rx = time.monotonic()        # time of the last message from the operator
        self.link_lost = False
        self._operator_offline = False
        self.blocked = False
        self._blocked_time = 0.0
        self.v = self.w = 0.0                  # last commanded body velocity (after ramp)
        self.tick_count = 0
        self.telem_count = 0
        self.stats = {"cmds": 0, "stale": 0, "rejected": 0, "pings": 0, "link_lost": 0,
                      "duplicates": 0}
        self._seen: "OrderedDict[tuple, bool]" = OrderedDict()   # recent (sid, seq) pairs
        self.trace: List[tuple] = []           # per-tick log (only if record_trace)
        self.events: List[tuple] = []          # (time, kind, details) for experiments
        self._stop = threading.Event()
        self.sim_time = 0.0

    # ---------------------------------------------------------------- network side
    def _on_message(self, msg: Dict[str, Any]) -> None:
        """Called from the transport thread for every received message."""
        self.last_rx = time.monotonic()
        kind = msg.get("type")
        if kind == "hb":
            return
        if kind == "cmd" and msg.get("cmd") == "ping":
            self.stats["pings"] += 1
            self.transport.send({"type": "pong", "seq": msg.get("seq"), "t_cmd": msg.get("t")})
            return
        self.inbox.put(msg)

    def _send(self, msg: Dict[str, Any]) -> None:
        self.transport.send(msg)

    def _send_result(self, res: Optional[Result]) -> None:
        if res is None:
            return
        self.events.append((time.monotonic(), "result", res.seq, res.outcome))
        self._send({"type": "result", "seq": res.seq, "cmd": res.cmd, "outcome": res.outcome,
                    "duration": round(res.duration, 3), "error": round(res.error, 4)})

    def _handle(self, msg: Dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "operator_status":
            self._operator_offline = not msg.get("online")
            if self._operator_offline:
                self._trip_watchdog("operator_offline")
            return
        if kind != "cmd":
            return
        seq = msg.get("seq")
        try:
            args = validate_cmd(msg)
        except ProtocolError as exc:
            self.stats["rejected"] += 1
            self._send({"type": "ack", "seq": seq, "ok": False, "err": str(exc)})
            return
        cmd = msg["cmd"]
        if msg.get("sid") is not None:
            key = (msg["sid"], seq)
            if key in self._seen:
                # MQTT QoS 1 may deliver a message twice: never execute it twice.
                self.stats["duplicates"] += 1
                self._send({"type": "ack", "seq": seq, "ok": True, "err": "duplicate ignored"})
                return
            self._seen[key] = True
            while len(self._seen) > 2000:
                self._seen.popitem(last=False)
        self.stats["cmds"] += 1
        sent_at = float(msg.get("t", time.time()))
        if self.safety.is_stale(cmd, sent_at, time.time()):
            self.stats["stale"] += 1
            self.events.append((time.monotonic(), "stale", seq, cmd))
            self._send({"type": "ack", "seq": seq, "ok": False,
                        "err": f"stale: command is {time.time() - sent_at:.2f} s old"})
            return
        self.link_lost = False
        self._operator_offline = False   # a fresh command proves the operator is there
        if cmd == "stop":
            self._send_result(self.controller.cancel("stopped"))
        elif cmd == "reset":
            self._send_result(self.controller.cancel("stopped"))
            self.backend.reset()
            self.v = self.w = 0.0
        elif cmd in MOTION_COMMANDS:
            self.events.append((time.monotonic(), "start", seq, cmd))
            self._send_result(self.controller.start(seq, cmd, args, self.backend.get_pose()))
            self._blocked_time = 0.0
        self._send({"type": "ack", "seq": seq, "ok": True, "err": None, "t_cmd": sent_at})
        if cmd == "status":
            self._send_telemetry()

    def _trip_watchdog(self, reason: str) -> None:
        if not self.link_lost:
            self.stats["link_lost"] += 1
            self.events.append((time.monotonic(), "link_lost", reason))
            if self.controller.mode != "idle":
                log.warning("link lost (%s): stopping robot", reason)
            else:
                log.info("no operator link (%s); robot is idle", reason)
        self.link_lost = True
        self._send_result(self.controller.cancel("link_lost"))

    # ---------------------------------------------------------------- control tick
    def tick(self) -> None:
        dt = self.p.dt
        while True:
            try:
                self._handle(self.inbox.get_nowait())
            except queue.Empty:
                break

        silent_for = time.monotonic() - self.last_rx
        if not self.safety.link_ok(silent_for):
            if not self.link_lost:
                self._trip_watchdog("watchdog")
        elif self.link_lost and not self._operator_offline:
            self.link_lost = False      # messages flow again; robot stays stopped until a new command

        pose = self.backend.get_pose()
        sonar = self.backend.get_sonar()
        v, w, res = self.controller.step(pose, dt)
        self._send_result(res)

        v, w, self.blocked = self.safety.filter(v, w, sonar)
        if self.blocked and self.controller.mode in ("move", "goto"):
            self._blocked_time += dt
            if self._blocked_time > self.p.safety.blocked_abort_time:
                self._send_result(self.controller.cancel("blocked"))
        else:
            self._blocked_time = 0.0

        # Speeding up is ramped; slowing down is immediate (safety first).
        rp = self.p.robot
        self.v = v if abs(v) < abs(self.v) else rate_limit(v, self.v, rp.max_accel, dt)
        self.w = rate_limit(w, self.w, rp.max_ang_accel, dt)
        wl, wr = unicycle_to_wheels(self.v, self.w, rp.wheel_radius, rp.wheel_base)
        wl, wr = saturate_wheels(wl, wr, rp.max_wheel_speed)
        self.backend.set_wheel_speeds(wl, wr)
        self.backend.step(dt)
        self.sim_time += dt
        self.tick_count += 1

        if self.p.record_trace:
            x, y, th = self.backend.get_pose()
            self.trace.append((time.monotonic(), self.sim_time, x, y, th, self.v, self.w,
                               self.state, self.controller.mode, front_distance(sonar)))
        every = max(1, round(self.p.control_rate_hz / self.p.telemetry_rate_hz))
        if self.tick_count % every == 0:
            self._send_telemetry(sonar)

    @property
    def state(self) -> str:
        if self.link_lost:
            return "LINK_LOST"
        if self.blocked:
            return "OBSTACLE"
        return "IDLE" if self.controller.mode == "idle" else "MOVING"

    def _send_telemetry(self, sonar=None) -> None:
        sonar = sonar if sonar is not None else self.backend.get_sonar()
        x, y, th = self.backend.get_pose()
        self.telem_count += 1
        self._send({"type": "telem", "t": time.time(), "n": self.telem_count,
                    "pose": [round(x, 4), round(y, 4), round(th, 4)],
                    "v": round(self.v, 3), "w": round(self.w, 3),
                    "state": self.state, "mode": self.controller.mode,
                    "active": self.controller.seq,
                    "obstacle": round(front_distance(sonar), 3)})

    # ---------------------------------------------------------------- main loop
    def start(self) -> None:
        self.transport.start(self._on_message)
        self.last_rx = time.monotonic()

    def run(self, duration: Optional[float] = None) -> None:
        """Run the fixed-rate loop until stop() is called (or for `duration` s)."""
        dt = self.p.dt
        t_next = time.monotonic()
        t_end = None if duration is None else t_next + duration
        while not self._stop.is_set():
            self.tick()
            t_next += dt
            now = time.monotonic()
            if t_end is not None and now >= t_end:
                break
            if t_next > now:
                self._stop.wait(t_next - now)
            elif now - t_next > 0.5:     # we fell far behind (e.g. laptop asleep): resync
                t_next = now

    def run_in_thread(self) -> threading.Thread:
        th = threading.Thread(target=self.run, daemon=True, name="robot-loop")
        th.start()
        return th

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        self.stop()
        try:
            self.backend.set_wheel_speeds(0.0, 0.0)
        finally:
            self.transport.close()
            self.backend.close()


# -------------------------------------------------------------------- CLI
def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Teleoperation robot server")
    ap.add_argument("--backend", choices=["mock", "coppelia"], default="mock")
    ap.add_argument("--transport", choices=["tcp", "mqtt"], default="tcp")
    ap.add_argument("--host", default=None,
                    help="tcp: address to listen on (default 0.0.0.0); mqtt: broker host (default 127.0.0.1)")
    ap.add_argument("--port", type=int, default=None, help="tcp: 9000, mqtt: 1883 by default")
    ap.add_argument("--qos", type=int, choices=[0, 1], default=1, help="MQTT QoS")
    ap.add_argument("--robot-id", default="p3dx", help="MQTT topic prefix teleop/<robot-id>/...")
    ap.add_argument("--keepalive", type=int, default=5, help="MQTT keepalive in seconds")
    ap.add_argument("--coppelia-host", default="localhost")
    ap.add_argument("--coppelia-port", type=int, default=23000)
    ap.add_argument("--watchdog", type=float, default=None, help="link watchdog timeout, s")
    ap.add_argument("--max-cmd-age", type=float, default=None, help="reject motion commands older than this, s")
    ap.add_argument("--duration", type=float, default=None, help="stop after this many seconds")
    ap.add_argument("-v", "--verbose", action="store_true")
    return ap


def main(argv=None) -> None:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    params = ServerParams()
    if args.watchdog is not None:
        params.safety.watchdog_timeout = args.watchdog
    if args.max_cmd_age is not None:
        params.safety.max_command_age = args.max_cmd_age

    if args.backend == "mock":
        backend = make_backend("mock", params=params.robot)
    else:
        backend = make_backend("coppelia", host=args.coppelia_host, port=args.coppelia_port,
                               params=params.robot)
    host = args.host or ("0.0.0.0" if args.transport == "tcp" else "127.0.0.1")
    port = args.port or (9000 if args.transport == "tcp" else 1883)
    transport = make_server(args.transport, host, port, robot_id=args.robot_id, qos=args.qos,
                            keepalive=args.keepalive)
    server = RobotServer(backend, transport, params)
    server.start()
    where = f"listening on {host}:{transport.port}" if args.transport == "tcp" else \
        f"broker {host}:{port}, topics teleop/{args.robot_id}/#, QoS {args.qos}"
    print(f"Robot server ready: backend={backend.name} transport={args.transport} ({where}). "
          f"Ctrl+C to stop.", flush=True)

    signal.signal(signal.SIGTERM, lambda *_: server.stop())
    try:
        server.run(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
        print(f"Server stopped. ticks={server.tick_count} commands={server.stats['cmds']} "
              f"stale={server.stats['stale']} link_lost={server.stats['link_lost']}", flush=True)


if __name__ == "__main__":
    main()
