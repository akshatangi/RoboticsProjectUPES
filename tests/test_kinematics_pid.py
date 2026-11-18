import math

import pytest

from teleop.kinematics import (integrate_pose, rate_limit, saturate_wheels, unicycle_to_wheels,
                               wheels_to_unicycle, wrap_angle)
from teleop.pid import PID

R, B = 0.0975, 0.331


def test_wrap_angle():
    assert wrap_angle(0.0) == 0.0
    assert wrap_angle(3 * math.pi) == pytest.approx(-math.pi)
    assert wrap_angle(-math.pi / 2) == pytest.approx(-math.pi / 2)
    assert wrap_angle(2 * math.pi + 0.1) == pytest.approx(0.1)


@pytest.mark.parametrize("v,w", [(0.3, 0.0), (0.0, 1.0), (0.4, -0.7), (-0.1, 0.2)])
def test_wheel_conversion_round_trip(v, w):
    wl, wr = unicycle_to_wheels(v, w, R, B)
    v2, w2 = wheels_to_unicycle(wl, wr, R, B)
    assert v2 == pytest.approx(v) and w2 == pytest.approx(w)


def test_pure_rotation_wheels_opposite():
    wl, wr = unicycle_to_wheels(0.0, 1.0, R, B)
    assert wl == pytest.approx(-wr) and wr > 0      # left turn: right wheel forward


def test_saturation_keeps_ratio():
    wl, wr = saturate_wheels(20.0, 10.0, 12.0)
    assert max(abs(wl), abs(wr)) == pytest.approx(12.0)
    assert wl / wr == pytest.approx(2.0)
    assert saturate_wheels(3.0, -4.0, 12.0) == (3.0, -4.0)


def test_integrate_straight_and_circle():
    assert integrate_pose(0, 0, 0, 1.0, 0.0, 2.0) == pytest.approx((2.0, 0.0, 0.0))
    # Quarter circle of radius 1: v=1, w=1 for pi/2 seconds ends at (1, 1, pi/2).
    x, y, th = integrate_pose(0, 0, 0, 1.0, 1.0, math.pi / 2)
    assert (x, y, th) == pytest.approx((1.0, 1.0, math.pi / 2))


def test_rate_limit():
    assert rate_limit(1.0, 0.0, 2.0, 0.1) == pytest.approx(0.2)
    assert rate_limit(-1.0, 0.0, 2.0, 0.1) == pytest.approx(-0.2)
    assert rate_limit(0.1, 0.0, 2.0, 0.1) == pytest.approx(0.1)


def test_pid_proportional_only():
    pid = PID(2.0)
    assert pid.update(0.5, 0.05) == pytest.approx(1.0)


def test_pid_integral_and_antiwindup():
    pid = PID(0.0, ki=1.0, i_limit=0.3)
    for _ in range(100):
        out = pid.update(1.0, 0.1)
    assert out == pytest.approx(0.3)                  # integral clamped


def test_pid_derivative_and_output_limit():
    pid = PID(0.0, kd=1.0, out_limit=5.0)
    assert pid.update(0.0, 0.1) == 0.0                # no derivative kick on first call
    assert pid.update(1.0, 0.1) == pytest.approx(5.0)  # 10 clipped to 5


def test_pid_rejects_bad_dt():
    with pytest.raises(ValueError):
        PID(1.0).update(1.0, 0.0)
