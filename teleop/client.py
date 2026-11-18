"""Operator-side API.

`OperatorClient` hides the network: you give it a command, it gives you back
a `Pending` object that fills in when the ack and the result arrive.  The
interactive shell (cli.py) and the experiment runner both use it.

    client = OperatorClient(make_client("tcp", "127.0.0.1", 9000))
    client.connect()
    p = client.send_line("move 1.0")
    client.wait_result(p, timeout=30)
    print(p.result["outcome"], client.telemetry["pose"])

A background thread sends a heartbeat 4 times per second so the robot's link
watchdog knows the operator is still there even when no command is typed.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .protocol import make_cmd, make_heartbeat, parse_command
from .transport import ClientTransport


@dataclass
class Pending:
    """One command we sent, and what came back for it."""

    seq: int
    cmd: str
    args: Dict[str, float]
    t_sent: float                       # time.monotonic() at send
    sent: bool = False                  # False if the transport refused it (link down)
    ack: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    t_ack: Optional[float] = None
    t_result: Optional[float] = None
    ack_event: threading.Event = field(default_factory=threading.Event)
    result_event: threading.Event = field(default_factory=threading.Event)

    @property
    def rtt(self) -> Optional[float]:
        """Seconds from sending to receiving the ack (or pong)."""
        return None if self.t_ack is None else self.t_ack - self.t_sent

    @property
    def ok(self) -> Optional[bool]:
        return None if self.ack is None else bool(self.ack.get("ok", True))


class OperatorClient:
    MAX_PENDING = 5000

    def __init__(self, transport: ClientTransport, heartbeat_interval: float = 0.25):
        self.transport = transport
        self.heartbeat_interval = heartbeat_interval
        self._seq = 0
        self.sid = uuid.uuid4().hex[:8]      # session id: makes (sid, seq) unique across restarts
        self._lock = threading.Lock()
        self.pending: "OrderedDict[int, Pending]" = OrderedDict()
        self.telemetry: Optional[Dict[str, Any]] = None
        self.telemetry_rx: Optional[float] = None      # monotonic time of last telemetry
        self.telem_count = 0
        self.duplicates = 0                             # replies for an unknown / already answered seq
        self.listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._log = None
        self._stop = threading.Event()

    # ------------------------------------------------------------ connection
    def connect(self, timeout: float = 5.0) -> None:
        self.transport.connect(self._on_message, timeout)
        threading.Thread(target=self._heartbeat_loop, daemon=True, name="heartbeat").start()

    def close(self) -> None:
        self._stop.set()
        self.log_stop()
        self.transport.close()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self.heartbeat_interval):
            self.transport.send(make_heartbeat())

    # ------------------------------------------------------------ receiving
    def _on_message(self, msg: Dict[str, Any]) -> None:
        now = time.monotonic()
        kind = msg.get("type")
        if kind == "telem":
            self.telemetry, self.telemetry_rx = msg, now
            self.telem_count += 1
            if self._log is not None:
                self._write_log(msg)
        elif kind in ("ack", "pong", "result"):
            p = self.pending.get(msg.get("seq"))  # type: ignore[arg-type]
            if p is None:
                self.duplicates += 1
            elif kind == "result":
                if p.result is None:
                    p.result, p.t_result = msg, now
                    p.result_event.set()
                else:
                    self.duplicates += 1
            else:
                if p.ack is None:
                    p.ack, p.t_ack = msg, now
                    p.ack_event.set()
                else:
                    self.duplicates += 1      # QoS 1 can deliver twice
        for fn in list(self.listeners):
            fn(msg)

    # ------------------------------------------------------------ sending
    def send_command(self, cmd: str, args: Optional[Dict[str, float]] = None) -> Pending:
        with self._lock:
            self._seq += 1
            seq = self._seq
        p = Pending(seq, cmd, args or {}, time.monotonic())
        self.pending[seq] = p
        while len(self.pending) > self.MAX_PENDING:
            self.pending.popitem(last=False)
        p.sent = self.transport.send(make_cmd(seq, cmd, args, sid=self.sid))
        return p

    def send_line(self, line: str) -> Pending:
        """Parse a typed command (raises ProtocolError) and send it."""
        parsed = parse_command(line)
        return self.send_command(parsed["cmd"], parsed["args"])

    def ping(self, timeout: float = 2.0) -> Optional[float]:
        """Round-trip time in seconds, or None if no pong came back in time."""
        p = self.send_command("ping")
        return p.rtt if p.ack_event.wait(timeout) else None

    @staticmethod
    def wait_ack(p: Pending, timeout: float = 5.0) -> bool:
        return p.ack_event.wait(timeout)

    @staticmethod
    def wait_result(p: Pending, timeout: float = 60.0) -> bool:
        return p.result_event.wait(timeout)

    def last_goal(self) -> Optional[Pending]:
        for p in reversed(self.pending.values()):
            if p.cmd in ("move", "turn", "goto"):
                return p
        return None

    # ------------------------------------------------------------ telemetry log
    def log_start(self, path: str) -> None:
        self.log_stop()
        self._log = open(path, "w", encoding="utf-8")
        self._log.write("t_recv,t_robot,x,y,theta,v,w,state,mode,obstacle\n")

    def log_stop(self) -> None:
        if self._log is not None:
            self._log.close()
            self._log = None

    def _write_log(self, m: Dict[str, Any]) -> None:
        x, y, th = m.get("pose", [0, 0, 0])
        self._log.write(f"{time.time():.3f},{m.get('t', 0):.3f},{x},{y},{th},{m.get('v')},{m.get('w')},"
                        f"{m.get('state')},{m.get('mode')},{m.get('obstacle')}\n")

    def telemetry_age(self) -> Optional[float]:
        return None if self.telemetry_rx is None else time.monotonic() - self.telemetry_rx

    def dump_telemetry(self) -> str:
        return json.dumps(self.telemetry) if self.telemetry else "{}"
