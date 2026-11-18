"""Differential-drive kinematics.

A differential-drive robot has two driven wheels on one axle.  If the right
wheel turns faster than the left one the robot curves to the left.

    v     = r * (wR + wL) / 2          forward speed            (m/s)
    omega = r * (wR - wL) / b          turn rate (counter-clockwise +) (rad/s)

with r = wheel radius, b = wheel base (track) and wR, wL the wheel angular
speeds in rad/s.  The inverse is used to turn a (v, omega) command into wheel
speeds.
"""

from __future__ import annotations

import math
from typing import Tuple


def wrap_angle(a: float) -> float:
    """Wrap an angle to the interval [-pi, pi)."""
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def unicycle_to_wheels(v: float, w: float, r: float, b: float) -> Tuple[float, float]:
    """(v, omega) -> (left, right) wheel angular speeds in rad/s."""
    w_left = (v - w * b / 2.0) / r
    w_right = (v + w * b / 2.0) / r
    return w_left, w_right


def wheels_to_unicycle(w_left: float, w_right: float, r: float, b: float) -> Tuple[float, float]:
    """(left, right) wheel speeds -> (v, omega)."""
    v = r * (w_right + w_left) / 2.0
    w = r * (w_right - w_left) / b
    return v, w


def saturate_wheels(w_left: float, w_right: float, w_max: float) -> Tuple[float, float]:
    """Scale both wheel speeds by the same factor so neither exceeds w_max.

    Scaling both keeps the ratio, so the robot follows the same curve, only
    slower.  Clipping each wheel separately would change the curve.
    """
    biggest = max(abs(w_left), abs(w_right))
    if biggest <= w_max or biggest == 0.0:
        return w_left, w_right
    k = w_max / biggest
    return w_left * k, w_right * k


def integrate_pose(x: float, y: float, th: float, v: float, w: float, dt: float) -> Tuple[float, float, float]:
    """Move the pose forward by dt using the exact arc solution.

    For a constant (v, w) the robot drives on a circle of radius v/w.  When w
    is almost zero we use the straight-line formula to avoid dividing by zero.
    """
    if abs(w) < 1e-9:
        return x + v * dt * math.cos(th), y + v * dt * math.sin(th), th
    th_new = th + w * dt
    radius = v / w
    x_new = x + radius * (math.sin(th_new) - math.sin(th))
    y_new = y - radius * (math.cos(th_new) - math.cos(th))
    return x_new, y_new, wrap_angle(th_new)


def rate_limit(target: float, current: float, max_rate: float, dt: float) -> float:
    """Move `current` towards `target` by at most max_rate*dt (acceleration limit)."""
    step = max_rate * dt
    if target > current + step:
        return current + step
    if target < current - step:
        return current - step
    return target
