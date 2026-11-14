"""The command language and the wire format.

Two layers:

1. **Text commands** that the operator types, for example::

       move 1.5 0.3        drive 1.5 m forward at 0.3 m/s
       turn 90             turn 90 degrees left (negative = right)
       goto 2 1            drive to the point x=2, y=1 (metres, world frame)
       vel 0.2 30          raw velocity: 0.2 m/s forward, 30 deg/s turn
       stop | status | ping | reset

   `parse_command()` turns one such line into a small dict, or raises
   `ProtocolError` with a message a human can understand.

2. **JSON messages** that travel over the network.  Every message is one
   JSON object; on TCP each object is followed by a newline (newline-delimited
   JSON), on MQTT each object is one MQTT payload.

   operator -> robot
       {"type": "cmd", "seq": 7, "sid": "3fa2c1d0", "t": 1730000000.12, "cmd": "move", "args": {"dist": 1.5, "speed": 0.3}}
       {"type": "hb",  "t": ...}                               heartbeat (keeps the watchdog happy)

   robot -> operator
       {"type": "ack",    "seq": 7, "ok": true,  "err": null}  command accepted / rejected
       {"type": "pong",   "seq": 8, "t_cmd": ...}               reply to ping
       {"type": "result", "seq": 7, "cmd": "move", "outcome": "reached", "duration": 5.1, "error": 0.01}
       {"type": "telem",  "t": ..., "pose": [x, y, th], "v": .., "w": .., "state": "MOVING",
                          "mode": "move", "obstacle": 0.84, "active": 7}

`seq` is a per-operator counter so every reply can be matched to the command
that caused it.  `sid` is a random id chosen once per operator session; the
robot ignores a second copy of the same (sid, seq), which MQTT QoS 1 is allowed
to deliver ("at least once").  `t` is the sender's wall-clock time in seconds; the robot uses
it to refuse motion commands that are too old (see safety.py).
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, List, Optional, Tuple


class ProtocolError(ValueError):
    """Raised for a command line or message that does not follow the protocol."""


# name -> list of (argument name, required?, default, help)
# All arguments are numbers.
COMMANDS: Dict[str, List[Tuple[str, bool, Optional[float], str]]] = {
    "move":   [("dist", True, None, "metres (negative = backwards)"),
               ("speed", False, 0.3, "m/s")],
    "turn":   [("angle", True, None, "degrees (positive = left / counter-clockwise)"),
               ("rate", False, 60.0, "deg/s")],
    "goto":   [("x", True, None, "metres"), ("y", True, None, "metres"),
               ("speed", False, 0.3, "m/s")],
    "vel":    [("v", True, None, "m/s"), ("w", True, None, "deg/s")],
    "stop":   [],
    "status": [],
    "ping":   [],
    "reset":  [],
}

MOTION_COMMANDS = {"move", "turn", "goto", "vel"}
# Commands that finish later and produce a "result" message.
GOAL_COMMANDS = {"move", "turn", "goto"}

HELP_TEXT = "\n".join(
    f"  {name:<7}" + " ".join(f"<{a}>" if req else f"[{a}={d:g}]" for a, req, d, _ in spec)
    for name, spec in COMMANDS.items()
)


def parse_command(line: str) -> Dict[str, Any]:
    """Parse one operator command line, e.g. ``"goto 2 1.5"``.

    Returns ``{"cmd": "goto", "args": {"x": 2.0, "y": 1.5, "speed": 0.3}}``.
    """
    parts = line.strip().split()
    if not parts:
        raise ProtocolError("empty command")
    name = parts[0].lower()
    if name not in COMMANDS:
        raise ProtocolError(f"unknown command '{name}'. Known: {', '.join(COMMANDS)}")
    spec = COMMANDS[name]
    values = parts[1:]
    if len(values) > len(spec):
        raise ProtocolError(f"'{name}' takes at most {len(spec)} argument(s), got {len(values)}")
    args: Dict[str, float] = {}
    for i, (arg, required, default, unit) in enumerate(spec):
        if i < len(values):
            try:
                num = float(values[i])
            except ValueError:
                raise ProtocolError(f"'{name}': {arg} must be a number ({unit}), got '{values[i]}'")
            if not math.isfinite(num):
                raise ProtocolError(f"'{name}': {arg} must be finite")
            args[arg] = num
        elif required:
            raise ProtocolError(f"'{name}' needs <{arg}> ({unit})")
        else:
            args[arg] = float(default)  # type: ignore[arg-type]
    for speed_arg in ("speed", "rate"):
        if speed_arg in args and args[speed_arg] <= 0:
            raise ProtocolError(f"'{name}': {speed_arg} must be positive")
    return {"cmd": name, "args": args}


# ---------------------------------------------------------------- messages

def make_cmd(seq: int, cmd: str, args: Optional[Dict[str, float]] = None,
             t: Optional[float] = None, sid: Optional[str] = None) -> Dict[str, Any]:
    msg = {"type": "cmd", "seq": seq, "t": time.time() if t is None else t,
           "cmd": cmd, "args": args or {}}
    if sid is not None:
        msg["sid"] = sid
    return msg


def make_heartbeat() -> Dict[str, Any]:
    return {"type": "hb", "t": time.time()}


def encode(msg: Dict[str, Any]) -> bytes:
    """Message -> bytes (compact JSON, UTF-8, no trailing newline)."""
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


def decode(data: bytes) -> Dict[str, Any]:
    """Bytes -> message.  Raises ProtocolError for anything malformed."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"bad JSON: {exc}") from None
    if not isinstance(msg, dict) or "type" not in msg:
        raise ProtocolError("message must be a JSON object with a 'type' field")
    return msg


def validate_cmd(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Check a received "cmd" message: known command, numeric arguments.

    Returns the args dict with defaults filled in.  Used by the robot so that a
    buggy or malicious client cannot crash the control loop.
    """
    cmd = msg.get("cmd")
    if cmd not in COMMANDS:
        raise ProtocolError(f"unknown command {cmd!r}")
    if not isinstance(msg.get("seq"), int):
        raise ProtocolError("'seq' must be an integer")
    raw = msg.get("args") or {}
    if not isinstance(raw, dict):
        raise ProtocolError("'args' must be an object")
    line = cmd + " " + " ".join(
        str(raw[a]) for a, _, _, _ in COMMANDS[cmd] if a in raw
    )
    # Re-use the text parser so both paths apply exactly the same rules.
    missing = [a for a, req, _, _ in COMMANDS[cmd] if req and a not in raw]
    if missing:
        raise ProtocolError(f"'{cmd}' missing argument(s): {', '.join(missing)}")
    return parse_command(line)["args"]


class LineBuffer:
    """Splits a TCP byte stream into newline-terminated messages.

    TCP is a byte stream, not a message stream: one recv() can return half a
    message or three messages at once.  We collect bytes until we see '\\n'.
    """

    MAX_LINE = 64 * 1024  # protects the robot from a client that never sends '\n'

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> List[bytes]:
        self._buf += data
        *lines, self._buf = self._buf.split(b"\n")
        if len(self._buf) > self.MAX_LINE:
            self._buf = b""
            raise ProtocolError("line too long")
        return [ln for ln in lines if ln.strip()]
