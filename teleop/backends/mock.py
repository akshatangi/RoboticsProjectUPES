"""Pure-Python mock of a Pioneer P3-DX in a small room.

Used when CoppeliaSim is not available (tests, CI, experiments on a laptop).
It models what matters for teleoperation:

* differential-drive kinematics (exact arc integration);
* motor lag - each wheel follows its command with a first-order lag
  (time constant `motor_tau`), so the robot does not stop instantly;
* 16 sonars (8 front, 8 rear, same angles as the P3-DX), each simulated as
  three rays over a 15-degree cone, range 1.0 m, small Gaussian noise;
* walls and box / cylinder obstacles, with collision detection (a collision
  freezes the robot for that step and is counted).

It does NOT model wheel slip, dynamics/inertia beyond the motor lag, or
sensor cross-talk.  Numbers produced with it are labelled "mock".
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..config import RobotParams
from ..kinematics import integrate_pose, wheels_to_unicycle
from .base import RobotBackend

Segment = Tuple[float, float, float, float]       # x1, y1, x2, y2
Circle = Tuple[float, float, float]               # cx, cy, r

# P3-DX sonar mounting angles in degrees: 0..7 front (left to right), 8..15 rear.
SONAR_ANGLES_DEG = [90, 50, 30, 10, -10, -30, -50, -90,
                    -90, -130, -150, -170, 170, 150, 130, 90]
SONAR_RANGE = 1.0
CONE_HALF_DEG = 7.5


@dataclass
class World:
    """Room geometry.  Default: a 7 m x 6 m room with one box and one cylinder."""

    segments: List[Segment] = field(default_factory=list)
    circles: List[Circle] = field(default_factory=list)

    @staticmethod
    def rect(x0: float, y0: float, x1: float, y1: float) -> List[Segment]:
        return [(x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)]

    @classmethod
    def default(cls) -> "World":
        w = cls()
        w.segments += cls.rect(-1.5, -1.5, 5.5, 4.5)       # outer walls
        w.segments += cls.rect(3.9, -0.3, 4.5, 0.3)        # 0.6 m box in front of the start
        w.circles.append((1.5, 4.0, 0.2))                  # cylinder near the top wall
        return w


def _ray_segment(px, py, dx, dy, seg: Segment) -> Optional[float]:
    """Distance along the ray (px,py)+t*(dx,dy) to the segment, or None."""
    x1, y1, x2, y2 = seg
    ex, ey = x2 - x1, y2 - y1
    denom = dx * ey - dy * ex
    if abs(denom) < 1e-12:
        return None
    t = ((x1 - px) * ey - (y1 - py) * ex) / denom
    u = ((x1 - px) * dy - (y1 - py) * dx) / denom
    if t >= 0 and 0 <= u <= 1:
        return t
    return None


def _ray_circle(px, py, dx, dy, c: Circle) -> Optional[float]:
    cx, cy, r = c
    fx, fy = px - cx, py - cy
    b = fx * dx + fy * dy
    cc = fx * fx + fy * fy - r * r
    disc = b * b - cc
    if disc < 0:
        return None
    t = -b - math.sqrt(disc)
    return t if t >= 0 else None


def _point_segment_distance(px, py, seg: Segment) -> float:
    x1, y1, x2, y2 = seg
    ex, ey = x2 - x1, y2 - y1
    L2 = ex * ex + ey * ey
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * ex + (py - y1) * ey) / L2))
    return math.hypot(px - (x1 + t * ex), py - (y1 + t * ey))


class MockBackend(RobotBackend):
    name = "mock"

    def __init__(self, params: Optional[RobotParams] = None, world: Optional[World] = None,
                 start_pose: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                 sonar_noise: float = 0.005, seed: Optional[int] = None):
        self.p = params or RobotParams()
        self.world = world or World.default()
        self.start_pose = start_pose
        self.sonar_noise = sonar_noise
        self.rng = random.Random(seed)
        self.reset()

    # ------------------------------------------------------------ interface
    def reset(self) -> None:
        self.x, self.y, self.th = self.start_pose
        self.cmd_l = self.cmd_r = 0.0       # commanded wheel speeds
        self.act_l = self.act_r = 0.0       # actual wheel speeds (after motor lag)
        self.time = 0.0
        self._collisions = 0

    def set_wheel_speeds(self, w_left: float, w_right: float) -> None:
        self.cmd_l, self.cmd_r = w_left, w_right

    def step(self, dt: float) -> None:
        # Motor lag: actual speed moves towards the command with time constant tau.
        a = 1.0 - math.exp(-dt / self.p.motor_tau)
        self.act_l += a * (self.cmd_l - self.act_l)
        self.act_r += a * (self.cmd_r - self.act_r)
        v, w = wheels_to_unicycle(self.act_l, self.act_r, self.p.wheel_radius, self.p.wheel_base)
        nx, ny, nth = integrate_pose(self.x, self.y, self.th, v, w, dt)
        if self._collides(nx, ny):
            # Blocked: the body cannot enter the obstacle; rotation is still possible.
            self._collisions += 1
            self.th = nth
            self.act_l = self.act_r = 0.0
        else:
            self.x, self.y, self.th = nx, ny, nth
        self.time += dt

    def get_pose(self) -> Tuple[float, float, float]:
        return self.x, self.y, self.th

    def get_wheel_speeds(self) -> Tuple[float, float]:
        return self.act_l, self.act_r

    def get_sonar(self) -> List[float]:
        return [self._sonar(math.radians(a)) for a in SONAR_ANGLES_DEG]

    def collisions(self) -> int:
        return self._collisions

    # ------------------------------------------------------------ geometry
    def clearance(self, x: Optional[float] = None, y: Optional[float] = None) -> float:
        """True distance from the robot body to the nearest obstacle (for metrics).

        Uses the current pose, or the given (x, y) when analysing a recorded trace."""
        x = self.x if x is None else x
        y = self.y if y is None else y
        d = min([_point_segment_distance(x, y, s) for s in self.world.segments] +
                [math.hypot(x - cx, y - cy) - r for cx, cy, r in self.world.circles])
        return d - self.p.body_radius

    def _collides(self, x: float, y: float) -> bool:
        r = self.p.body_radius
        for s in self.world.segments:
            if _point_segment_distance(x, y, s) < r:
                return True
        for cx, cy, cr in self.world.circles:
            if math.hypot(x - cx, y - cy) < r + cr:
                return True
        return False

    def _sonar(self, mount: float) -> float:
        # Sensor sits on the body circle, looking outwards.
        ang = self.th + mount
        sx = self.x + self.p.body_radius * math.cos(ang)
        sy = self.y + self.p.body_radius * math.sin(ang)
        best = SONAR_RANGE
        for off in (-CONE_HALF_DEG, 0.0, CONE_HALF_DEG):
            a = ang + math.radians(off)
            dx, dy = math.cos(a), math.sin(a)
            for s in self.world.segments:
                t = _ray_segment(sx, sy, dx, dy, s)
                if t is not None and t < best:
                    best = t
            for c in self.world.circles:
                t = _ray_circle(sx, sy, dx, dy, c)
                if t is not None and t < best:
                    best = t
        if best < SONAR_RANGE and self.sonar_noise > 0:
            best = max(0.0, best + self.rng.gauss(0.0, self.sonar_noise))
        return best
