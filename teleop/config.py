"""All tunable numbers in one place.

Everything the robot side needs (robot geometry, controller gains, safety
limits, loop rates) lives in plain dataclasses so that experiments and tests
can override single values without touching the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RobotParams:
    """Pioneer P3-DX geometry and limits.

    Wheel radius 0.0975 m and track 0.331 m follow the P3-DX data sheet
    (195 mm wheels).  The team must check both against the CoppeliaSim model
    (docs/SCENE_SETUP.md, step 6) and change them here if they differ.
    """

    wheel_radius: float = 0.0975       # m
    wheel_base: float = 0.331          # m, distance between the two wheels
    body_radius: float = 0.26          # m, circle that encloses the robot body
    max_wheel_speed: float = 12.0      # rad/s per wheel  (~1.17 m/s at the rim)
    max_v: float = 0.7                 # m/s, software limit on forward speed
    max_w: float = 2.0                 # rad/s, software limit on turn rate
    max_reverse_v: float = 0.2         # m/s, reversing is slow (no rear safety stop margin)
    max_accel: float = 1.0             # m/s^2, ramp limit on v
    max_ang_accel: float = 4.0         # rad/s^2, ramp limit on w
    motor_tau: float = 0.08            # s, first-order wheel lag used by the mock


@dataclass
class ControlGains:
    """PID gains for the motion primitives (tuned in experiments/pid_tuning.py)."""

    heading_kp: float = 3.0
    heading_ki: float = 0.0
    heading_kd: float = 0.15
    dist_kp: float = 1.2               # m/s per metre of remaining distance
    pos_tolerance: float = 0.03        # m, "arrived" for move / goto
    ang_tolerance_deg: float = 1.5     # deg, "arrived" for turn
    settle_time: float = 0.15          # s, must stay inside tolerance this long


@dataclass
class SafetyParams:
    stop_distance: float = 0.30        # m, obstacle closer than this -> no forward motion
    slow_distance: float = 0.80        # m, start slowing down below this
    creep_speed: float = 0.05          # m/s, minimum speed inside the slow zone
    release_margin: float = 0.05       # m, hysteresis: blocked until stop_distance + this
    watchdog_timeout: float = 1.0      # s without any operator message -> stop (LINK_LOST)
    max_command_age: float = 1.0       # s, motion commands older than this are rejected
    blocked_abort_time: float = 2.0    # s blocked by an obstacle -> abort move/goto


@dataclass
class ServerParams:
    control_rate_hz: float = 20.0      # control loop (and simulation step) frequency
    telemetry_rate_hz: float = 10.0    # telemetry messages per second
    robot: RobotParams = field(default_factory=RobotParams)
    gains: ControlGains = field(default_factory=ControlGains)
    safety: SafetyParams = field(default_factory=SafetyParams)
    record_trace: bool = False         # keep a per-tick log (used by experiments)

    @property
    def dt(self) -> float:
        return 1.0 / self.control_rate_hz
