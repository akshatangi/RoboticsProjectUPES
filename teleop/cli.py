"""Interactive operator shell.

    python -m teleop.cli --transport tcp --host 127.0.0.1 --port 9000

Robot commands (sent over the network):
    move <dist> [speed]     turn <deg> [rate]     goto <x> <y> [speed]
    vel <v> <w_deg>         stop     status     ping     reset

Shell commands (handled locally):
    help                    show this help
    wait [seconds]          no number: wait until the last move/turn/goto finishes
    watch [seconds]         print live telemetry (default 5 s, Ctrl+C ends early)
    rtt [n]                 send n pings (default 10) and print round-trip statistics
    log start <file.csv>    record every telemetry message to a CSV file
    log stop
    macro <file>            run the commands in a file, one per line ('#' = comment)
    history                 list the commands typed in this session
    quit / exit             leave (the robot stops by itself: watchdog)

Non-interactive use (handy for demos and tests):
    python -m teleop.cli -c "move 1; wait; turn 90; wait; status"
    python -m teleop.cli --script macros/square.tlm
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from typing import List, Optional

from .client import OperatorClient, Pending
from .protocol import GOAL_COMMANDS, HELP_TEXT, ProtocolError
from .transport import make_client

try:  # readline gives arrow-key history on Linux/macOS; optional on Windows
    import readline  # noqa: F401
    HAVE_READLINE = True
except ImportError:  # pragma: no cover
    HAVE_READLINE = False

HISTORY_FILE = os.path.expanduser("~/.teleop_history")
LOCAL_HELP = """Shell commands:
  wait [s]               wait s seconds, or (no number) until the last move/turn/goto finishes
  watch [s]              live telemetry for s seconds (default 5)
  rtt [n]                n pings, print min/mean/max round-trip time
  log start <file.csv>   record telemetry to CSV      log stop
  macro <file>           run a command file           history     help     quit"""


def fmt_telemetry(t: Optional[dict]) -> str:
    if not t:
        return "no telemetry yet"
    x, y, th = t["pose"]
    return (f"pose x={x:+.3f} m  y={y:+.3f} m  th={th * 57.29578:+7.2f} deg | "
            f"v={t['v']:+.2f} m/s w={t['w']:+.2f} rad/s | {t['state']:<9} mode={t['mode']:<5} "
            f"obstacle={t['obstacle']:.2f} m")


class Shell:
    def __init__(self, client: OperatorClient, out=sys.stdout, echo: bool = False):
        self.client = client
        self.out = out
        self.echo = echo                # print each command (script mode)
        self.history: List[str] = []
        self.last_goal: Optional[Pending] = None
        client.listeners.append(self._on_event)

    def say(self, text: str) -> None:
        print(text, file=self.out, flush=True)

    # Results arrive in the background; print them as soon as they come.
    def _on_event(self, msg: dict) -> None:
        if msg.get("type") == "error":
            self.say(f"  !! robot says: {msg.get('err')}")
        elif msg.get("type") == "result":
            p = self.client.pending.get(msg.get("seq"))
            took = f" after {msg['duration']:.2f} s" if "duration" in msg else ""
            unit = "deg" if msg.get("cmd") == "turn" else "m"
            self.say(f"  <- result #{msg['seq']} {msg.get('cmd')}: {msg['outcome']}{took}, "
                     f"final error {msg.get('error', 0):.3f} {unit}" + ("" if p else " (unknown seq)"))

    # ------------------------------------------------------------ dispatch
    def execute(self, line: str) -> bool:
        """Run one line.  Returns False when the user wants to quit."""
        line = line.split("#", 1)[0].strip()
        if not line:
            return True
        self.history.append(line)
        if self.echo:
            self.say(f"teleop> {line}")
        word, *rest = line.split()
        word = word.lower()
        local = getattr(self, "do_" + word, None)
        if local is not None:
            return local(rest) is not False
        self._robot_command(line)
        return True

    def _robot_command(self, line: str) -> None:
        try:
            p = self.client.send_line(line)
        except ProtocolError as exc:
            self.say(f"  error: {exc}  (type 'help')")
            return
        if not p.sent:
            self.say(f"  !! #{p.seq} not sent: link is down")
            return
        if p.cmd in GOAL_COMMANDS:
            self.last_goal = p
        if not self.client.wait_ack(p, 3.0):
            self.say(f"  !! #{p.seq} no reply within 3 s (still queued if MQTT QoS 1)")
            return
        if p.cmd == "ping":
            self.say(f"  <- pong #{p.seq} rtt={p.rtt * 1000:.1f} ms")
        elif not p.ok:
            self.say(f"  <- #{p.seq} REJECTED: {p.ack.get('err')}")
        elif p.cmd == "status":
            time.sleep(0.05)
            self.say("  " + fmt_telemetry(self.client.telemetry))
        else:
            self.say(f"  <- ack #{p.seq} {p.cmd} ok ({p.rtt * 1000:.1f} ms)")

    # ------------------------------------------------------------ local commands
    def do_help(self, args):
        self.say("Robot commands:\n" + HELP_TEXT + "\n" + LOCAL_HELP)

    def do_quit(self, args):
        return False

    do_exit = do_quit

    def do_history(self, args):
        for i, h in enumerate(self.history[:-1], 1):
            self.say(f"  {i:3d}  {h}")

    def do_wait(self, args):
        if args:
            try:
                time.sleep(float(args[0]))
            except ValueError:
                self.say("  usage: wait [seconds]")
            return
        p = self.last_goal
        if p is None:
            self.say("  nothing to wait for")
            return
        if not self.client.wait_result(p, 120.0):
            self.say(f"  !! no result for #{p.seq} within 120 s")

    def do_watch(self, args):
        seconds = float(args[0]) if args else 5.0
        end = time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                age = self.client.telemetry_age()
                age_s = "  (no data)" if age is None else f"  age={age * 1000:4.0f} ms"
                self.say("  " + fmt_telemetry(self.client.telemetry) + age_s)
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    def do_rtt(self, args):
        n = int(args[0]) if args else 10
        rtts = [r for r in (self.client.ping() for _ in range(n)) if r is not None]
        if not rtts:
            self.say("  no replies")
            return
        ms = [r * 1000 for r in rtts]
        self.say(f"  {len(ms)}/{n} replies  min {min(ms):.1f}  mean {statistics.mean(ms):.1f}  "
                 f"max {max(ms):.1f} ms")

    def do_log(self, args):
        if args[:1] == ["start"] and len(args) == 2:
            self.client.log_start(args[1])
            self.say(f"  logging telemetry to {args[1]}")
        elif args[:1] == ["stop"]:
            self.client.log_stop()
            self.say("  logging stopped")
        else:
            self.say("  usage: log start <file.csv> | log stop")

    def do_macro(self, args):
        if not args:
            self.say("  usage: macro <file>")
            return
        try:
            with open(args[0], encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError as exc:
            self.say(f"  cannot open macro: {exc}")
            return
        old, self.echo = self.echo, True
        try:
            for ln in lines:
                if not self.execute(ln):
                    return False
        finally:
            self.echo = old

    # ------------------------------------------------------------ interactive loop
    def loop(self) -> None:
        if HAVE_READLINE:
            try:
                readline.read_history_file(HISTORY_FILE)
            except OSError:
                pass
        self.say("Type 'help' for commands, 'quit' to leave.")
        try:
            while True:
                try:
                    line = input("teleop> ")
                except EOFError:
                    break
                except KeyboardInterrupt:
                    self.say("")
                    self._robot_command("stop")   # Ctrl+C = emergency stop, not exit
                    continue
                if not self.execute(line):
                    break
        finally:
            if HAVE_READLINE:
                try:
                    readline.write_history_file(HISTORY_FILE)
                except OSError:
                    pass


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Teleoperation operator shell")
    ap.add_argument("--transport", choices=["tcp", "mqtt"], default="tcp")
    ap.add_argument("--host", default="127.0.0.1", help="robot (tcp) or broker (mqtt) address")
    ap.add_argument("--port", type=int, default=None, help="tcp: 9000, mqtt: 1883 by default")
    ap.add_argument("--qos", type=int, choices=[0, 1], default=1)
    ap.add_argument("--robot-id", default="p3dx")
    ap.add_argument("--keepalive", type=int, default=5)
    ap.add_argument("-c", "--commands", help="run ';'-separated commands and exit")
    ap.add_argument("--script", help="run a command file and exit")
    return ap


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    port = args.port or (9000 if args.transport == "tcp" else 1883)
    transport = make_client(args.transport, args.host, port, robot_id=args.robot_id,
                            qos=args.qos, keepalive=args.keepalive)
    client = OperatorClient(transport)
    try:
        client.connect(timeout=5.0)
    except ConnectionError as exc:
        print(f"Could not connect: {exc}", file=sys.stderr)
        return 1
    print(f"Connected via {args.transport} to {args.host}:{port}"
          + (f" (robot '{args.robot_id}', QoS {args.qos})" if args.transport == "mqtt" else ""), flush=True)
    shell = Shell(client)
    try:
        if args.commands:
            shell.echo = True
            for part in args.commands.split(";"):
                if not shell.execute(part):
                    break
        elif args.script:
            shell.do_macro([args.script])
        else:
            shell.loop()
    finally:
        time.sleep(0.2)          # let the last result print
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
