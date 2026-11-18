"""Safety layer: runs on the robot, after the controller, every tick.

The network can be slow or can disappear, so safety must NOT depend on the
operator.  Three independent guards:

1. Obstacle guard - uses the sonar ring.  Closer than `slow_distance` the
   forward speed is scaled down linearly; closer than `stop_distance` forward
   motion is blocked completely (turning on the spot is still allowed so the
   operator can steer away).  The same rule applies to reversing with the
   rear sonars.
2. Link watchdog - if no message (command or heartbeat) arrived for
   `watchdog_timeout` seconds, the robot stops and enters LINK_LOST.
3. Stale-command guard - a motion command whose send time is older than
   `max_command_age` is rejected instead of executed (a late "go forward"
   is dangerous; a late "stop" is always accepted).
"""

from __future__ import annotations

from typing import Sequence, Tuple

from .config import SafetyParams

# Indices into the 16-sonar ring of the Pioneer P3-DX (0..7 front, 8..15 rear).
# Sensors 2..5 look forward (+-10 and +-30 deg); 10..13 look backward.
FRONT_SONARS = (2, 3, 4, 5)
FRONT_WIDE = (1, 2, 3, 4, 5, 6)
REAR_SONARS = (10, 11, 12, 13)


def front_distance(sonar: Sequence[float]) -> float:
    return min(sonar[i] for i in FRONT_SONARS)


def rear_distance(sonar: Sequence[float]) -> float:
    return min(sonar[i] for i in REAR_SONARS)


class SafetyLayer:
    def __init__(self, params: SafetyParams):
        self.p = params
        # Hysteresis: once blocked, stay blocked until the obstacle is
        # `release_margin` further away.  Without it, sonar noise around the
        # stop line makes the robot stop-go-stop and creep forward.
        self._blocked = {"front": False, "rear": False}

    def _factor(self, side: str, distance: float) -> float:
        if self._blocked[side] and distance < self.p.stop_distance + self.p.release_margin:
            return 0.0
        k = self.speed_factor(distance)
        self._blocked[side] = k == 0.0
        return k

    def speed_factor(self, distance: float) -> float:
        """1.0 far away, falls linearly to 0.0 at stop_distance."""
        if distance <= self.p.stop_distance:
            return 0.0
        if distance >= self.p.slow_distance:
            return 1.0
        return (distance - self.p.stop_distance) / (self.p.slow_distance - self.p.stop_distance)

    def filter(self, v: float, w: float, sonar: Sequence[float]) -> Tuple[float, float, bool]:
        """Apply the obstacle guard.  Returns (v, w, blocked)."""
        if v > 0:
            k = self._factor("front", front_distance(sonar))
        elif v < 0:
            k = self._factor("rear", rear_distance(sonar))
        else:
            return v, w, False
        if k == 0.0:
            return 0.0, w, True
        # Inside the slow zone keep at least a slow creep; otherwise the speed
        # would shrink forever and the robot would never reach the stop line.
        creep = min(abs(v), self.p.creep_speed)
        scaled = max(abs(v) * k, creep)
        return (scaled if v > 0 else -scaled), w, False

    def link_ok(self, seconds_since_last_message: float) -> bool:
        return seconds_since_last_message <= self.p.watchdog_timeout

    def is_stale(self, cmd: str, sent_at: float, now: float) -> bool:
        """True if a motion command is too old to execute safely."""
        if cmd not in ("move", "turn", "goto", "vel"):
            return False
        return (now - sent_at) > self.p.max_command_age
