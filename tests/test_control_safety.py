"""Controller + safety + mock backend, without any network."""

import math

import pytest

from teleop.backends import MockBackend, World
from teleop.config import ControlGains, RobotParams, SafetyParams
from teleop.controller import MotionController
from teleop.kinematics import unicycle_to_wheels
from teleop.safety import SafetyLayer

DT = 0.05


def run(ctrl, robot, steps=600, safety=None):
    """Closed loop on the mock robot until the controller reports a result."""
    for _ in range(steps):
        pose = robot.get_pose()
        v, w, res = ctrl.step(pose, DT)
        if safety is not None:
            v, w, _ = safety.filter(v, w, robot.get_sonar())
        robot.set_wheel_speeds(*unicycle_to_wheels(v, w, robot.p.wheel_radius, robot.p.wheel_base))
        robot.step(DT)
        if res is not None:
            return res
    return None


@pytest.fixture
def setup():
    rp = RobotParams()
    return MotionController(rp, ControlGains()), MockBackend(rp, World(), sonar_noise=0.0)


def test_move_reaches_distance(setup):
    ctrl, robot = setup
    ctrl.start(1, "move", {"dist": 1.0, "speed": 0.4}, robot.get_pose())
    res = run(ctrl, robot)
    assert res.outcome == "reached"
    assert robot.get_pose()[0] == pytest.approx(1.0, abs=0.05)
    assert abs(robot.get_pose()[1]) < 0.01


def test_move_backwards_is_slow(setup):
    ctrl, robot = setup
    ctrl.start(1, "move", {"dist": -0.3, "speed": 1.0}, robot.get_pose())
    assert ctrl._target["speed"] == RobotParams().max_reverse_v
    assert run(ctrl, robot).outcome == "reached"
    assert robot.get_pose()[0] == pytest.approx(-0.3, abs=0.05)


@pytest.mark.parametrize("angle", [90, -45, 180])
def test_turn_reaches_heading(setup, angle):
    ctrl, robot = setup
    ctrl.start(1, "turn", {"angle": angle, "rate": 90}, robot.get_pose())
    res = run(ctrl, robot)
    assert res.outcome == "reached"
    err = (math.degrees(robot.get_pose()[2]) - angle + 180) % 360 - 180
    assert abs(err) < 2.5


def test_goto_reaches_point(setup):
    ctrl, robot = setup
    ctrl.start(1, "goto", {"x": 1.0, "y": -1.0, "speed": 0.4}, robot.get_pose())
    res = run(ctrl, robot, steps=800)
    assert res.outcome == "reached"
    x, y, _ = robot.get_pose()
    assert math.hypot(x - 1.0, y + 1.0) < 0.05


def test_new_command_preempts_old(setup):
    ctrl, robot = setup
    ctrl.start(1, "move", {"dist": 2.0, "speed": 0.3}, robot.get_pose())
    prev = ctrl.start(2, "turn", {"angle": 10, "rate": 30}, robot.get_pose())
    assert prev.seq == 1 and prev.outcome == "preempted"


def test_vel_is_clamped(setup):
    ctrl, _ = setup
    ctrl.start(1, "vel", {"v": 5.0, "w": 999.0}, (0, 0, 0))
    v, w, _ = ctrl.step((0, 0, 0), DT)
    assert v == RobotParams().max_v and w == RobotParams().max_w


def test_timeout(setup):
    ctrl, _ = setup
    ctrl.start(1, "move", {"dist": 1.0, "speed": 0.5}, (0, 0, 0))
    res = None
    for _ in range(1000):                   # robot never moves -> must time out
        _, _, res = ctrl.step((0, 0, 0), DT)
        if res:
            break
    assert res.outcome == "timeout"


# ----------------------------------------------------------------- safety
def test_speed_factor():
    s = SafetyLayer(SafetyParams(stop_distance=0.3, slow_distance=0.8))
    assert s.speed_factor(1.0) == 1.0
    assert s.speed_factor(0.3) == 0.0
    assert s.speed_factor(0.55) == pytest.approx(0.5)


def test_filter_blocks_forward_but_allows_turning():
    s = SafetyLayer(SafetyParams())
    sonar = [1.0] * 16
    sonar[3] = 0.2                         # obstacle straight ahead
    v, w, blocked = s.filter(0.5, 0.4, sonar)
    assert v == 0.0 and w == 0.4 and blocked
    v, w, blocked = s.filter(-0.1, 0.0, sonar)   # reversing away is fine
    assert v == -0.1 and not blocked


def test_hysteresis_holds_block_until_release_margin():
    s = SafetyLayer(SafetyParams(stop_distance=0.30, release_margin=0.05))
    sonar = [1.0] * 16
    sonar[3] = 0.29
    assert s.filter(0.3, 0.0, sonar)[2]            # blocked
    sonar[3] = 0.31                                # noise pushes it just past the stop line
    v, _, blocked = s.filter(0.3, 0.0, sonar)
    assert blocked and v == 0.0                    # still blocked (needs 0.35)
    sonar[3] = 0.36
    v, _, blocked = s.filter(0.3, 0.0, sonar)
    assert not blocked and v > 0


def test_stale_guard():
    s = SafetyLayer(SafetyParams(max_command_age=1.0))
    assert s.is_stale("move", sent_at=0.0, now=1.5)
    assert not s.is_stale("move", sent_at=1.0, now=1.5)
    assert not s.is_stale("stop", sent_at=0.0, now=100.0)   # a late stop is always welcome


def test_obstacle_stop_prevents_collision():
    rp = RobotParams()
    world = World(segments=World.rect(-5, -5, 2.0, 5))   # wall at x = 2
    robot = MockBackend(rp, world, sonar_noise=0.0)
    ctrl = MotionController(rp, ControlGains())
    ctrl.start(1, "vel", {"v": 0.7, "w": 0.0}, robot.get_pose())
    run(ctrl, robot, steps=200, safety=SafetyLayer(SafetyParams()))
    assert robot.collisions() == 0
    assert 0.2 < robot.clearance() < 0.35


def count_stop_go_toggles(release_margin: float) -> int:
    rp = RobotParams()
    robot = MockBackend(rp, World(segments=World.rect(-5, -5, 2.0, 5)), sonar_noise=0.01, seed=3)
    safety = SafetyLayer(SafetyParams(release_margin=release_margin))
    toggles, prev = 0, None
    for _ in range(500):                                # 25 s pushing at the wall with vel 0.5
        v, _, blocked = safety.filter(0.5, 0.0, robot.get_sonar())
        if prev is not None and blocked != prev:
            toggles += 1
        prev = blocked
        robot.set_wheel_speeds(*unicycle_to_wheels(v, 0.0, rp.wheel_radius, rp.wheel_base))
        robot.step(DT)
    return toggles


def test_no_stop_go_chatter_at_stop_line():
    """Regression: sonar noise around the stop line made the robot stop-go-stop."""
    assert count_stop_go_toggles(0.0) > 5               # the old behaviour chatters ...
    assert count_stop_go_toggles(0.05) == 1             # ... with hysteresis: one clean stop


# ----------------------------------------------------------------- mock robot
def test_mock_sonar_sees_wall():
    world = World(segments=World.rect(-5, -5, 1.0, 5))
    robot = MockBackend(RobotParams(), world, sonar_noise=0.0)
    sonar = robot.get_sonar()
    # sonar 3 points 10 deg left; its centre ray hits x=1 at (1-0.26*cos10)/cos10, the
    # lower cone edge (2.5 deg) is a bit shorter - the sensor reports the shortest ray.
    assert sonar[3] == pytest.approx((1.0 - 0.26 * math.cos(math.radians(10))) / math.cos(math.radians(2.5)), abs=0.01)
    assert sonar[0] == 1.0                 # looking left: nothing within range


def test_mock_counts_collisions_without_safety():
    world = World(segments=World.rect(-5, -5, 0.5, 5))
    robot = MockBackend(RobotParams(), world)
    robot.set_wheel_speeds(5.0, 5.0)
    for _ in range(40):
        robot.step(DT)
    assert robot.collisions() > 0
    assert robot.get_pose()[0] < 0.5 - 0.26 + 1e-6
