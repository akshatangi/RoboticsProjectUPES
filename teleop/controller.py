"""Motion primitives: move, turn, goto and raw velocity.

The controller is called once per control tick with the current pose and
returns the desired body velocity (v, omega).  It never talks to the network
or to the robot directly - that is the server's job - which makes it easy to
unit-test.

    move  dist speed   drive straight; a heading PID keeps the start heading,
                       a P-controller on the remaining distance slows down at
                       the end.
    turn  angle rate   rotate in place; heading PID on the target heading.
    goto  x y speed    go-to-goal: heading PID points at the goal, forward
                       speed is reduced while the heading error is large.
    vel   v w          pass the operator's velocities through (clamped).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from .config import ControlGains, RobotParams
from .kinematics import wrap_angle
from .pid import PID

Pose = Tuple[float, float, float]


@dataclass
class Result:
    """Outcome of a finished goal command (move/turn/goto)."""

    seq: int
    cmd: str
    outcome: str        # reached | stopped | preempted | blocked | link_lost | timeout
    duration: float     # s, from start to finish
    error: float        # final position error (m) or heading error (deg) for turn


class MotionController:
    def __init__(self, robot: RobotParams, gains: ControlGains):
        self.robot = robot
        self.gains = gains
        self.heading_pid = PID(gains.heading_kp, gains.heading_ki, gains.heading_kd,
                               out_limit=robot.max_w, i_limit=0.5)
        self.mode = "idle"
        self.seq: Optional[int] = None
        self._target: dict = {}
        self._elapsed = 0.0
        self._settled = 0.0
        self._timeout = 0.0
        self._last_error = 0.0

    # ------------------------------------------------------------ commands
    def start(self, seq: int, cmd: str, args: dict, pose: Pose) -> Optional[Result]:
        """Begin a new motion command.  Returns a 'preempted' result for the
        previous goal command if one was still running."""
        previous = self.cancel("preempted")
        x, y, th = pose
        self.heading_pid.reset()
        self.seq, self.mode = seq, cmd
        self._elapsed = self._settled = 0.0
        if cmd == "move":
            speed = min(abs(args["speed"]), self.robot.max_v)
            if args["dist"] < 0:
                speed = min(speed, self.robot.max_reverse_v)
            self._target = {"x0": x, "y0": y, "th": th, "dist": args["dist"], "speed": speed}
            self._timeout = abs(args["dist"]) / speed * 2.0 + 5.0
        elif cmd == "turn":
            rate = min(math.radians(abs(args["rate"])), self.robot.max_w)
            angle = math.radians(args["angle"])
            self._target = {"th": wrap_angle(th + angle), "rate": rate}
            self._timeout = abs(angle) / rate * 2.0 + 5.0
        elif cmd == "goto":
            speed = min(abs(args["speed"]), self.robot.max_v)
            self._target = {"x": args["x"], "y": args["y"], "speed": speed}
            dist = math.hypot(args["x"] - x, args["y"] - y)
            self._timeout = dist / speed * 2.0 + 10.0
        elif cmd == "vel":
            v = max(-self.robot.max_reverse_v, min(self.robot.max_v, args["v"]))
            w = math.radians(args["w"])
            w = max(-self.robot.max_w, min(self.robot.max_w, w))
            self._target = {"v": v, "w": w}
            self._timeout = float("inf")
        else:
            raise ValueError(f"not a motion command: {cmd}")
        return previous

    def cancel(self, outcome: str) -> Optional[Result]:
        """Stop whatever is running.  Returns a Result if a goal was active."""
        result = None
        if self.mode in ("move", "turn", "goto") and self.seq is not None:
            result = Result(self.seq, self.mode, outcome, self._elapsed, self._last_error)
        self.mode, self.seq, self._target = "idle", None, {}
        return result

    # ------------------------------------------------------------ control step
    def step(self, pose: Pose, dt: float) -> Tuple[float, float, Optional[Result]]:
        """One control tick.  Returns (v, omega, finished_result_or_None)."""
        if self.mode == "idle":
            return 0.0, 0.0, None
        self._elapsed += dt
        if self._elapsed > self._timeout:
            return 0.0, 0.0, self.cancel("timeout")
        handler = getattr(self, "_step_" + self.mode)
        v, w, done = handler(pose, dt)
        if done:
            seq, mode, err = self.seq, self.mode, self._last_error
            self.mode, self.seq, self._target = "idle", None, {}
            return 0.0, 0.0, Result(seq, mode, "reached", self._elapsed, err)  # type: ignore[arg-type]
        return v, w, None

    def _settle(self, inside: bool, dt: float) -> bool:
        """True once the error has stayed inside the tolerance for settle_time."""
        self._settled = self._settled + dt if inside else 0.0
        return self._settled >= self.gains.settle_time

    def _step_move(self, pose: Pose, dt: float):
        x, y, th = pose
        t = self._target
        # Progress = distance travelled along the starting heading.
        travelled = (x - t["x0"]) * math.cos(t["th"]) + (y - t["y0"]) * math.sin(t["th"])
        remaining = t["dist"] - travelled
        self._last_error = abs(remaining)
        v = max(-t["speed"], min(t["speed"], self.gains.dist_kp * remaining))
        w = self.heading_pid.update(wrap_angle(t["th"] - th), dt)
        return v, w, self._settle(abs(remaining) < self.gains.pos_tolerance, dt)

    def _step_turn(self, pose: Pose, dt: float):
        err = wrap_angle(self._target["th"] - pose[2])
        self._last_error = abs(math.degrees(err))
        w = self.heading_pid.update(err, dt)
        w = max(-self._target["rate"], min(self._target["rate"], w))
        inside = self._last_error < self.gains.ang_tolerance_deg
        return 0.0, w, self._settle(inside, dt)

    def _step_goto(self, pose: Pose, dt: float):
        x, y, th = pose
        t = self._target
        dx, dy = t["x"] - x, t["y"] - y
        dist = math.hypot(dx, dy)
        self._last_error = dist
        if dist < self.gains.pos_tolerance:
            return 0.0, 0.0, self._settle(True, dt)
        self._settled = 0.0
        heading_err = wrap_angle(math.atan2(dy, dx) - th)
        w = self.heading_pid.update(heading_err, dt)
        # cos() term: full speed when facing the goal, zero when it is 90+ deg off,
        # so the robot turns on the spot first instead of driving a wide arc.
        v = min(t["speed"], self.gains.dist_kp * dist) * max(0.0, math.cos(heading_err)) ** 2
        return v, w, False

    def _step_vel(self, pose: Pose, dt: float):
        return self._target["v"], self._target["w"], False
