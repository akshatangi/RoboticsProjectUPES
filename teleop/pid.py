"""A small, readable PID controller.

    u(t) = Kp * e(t) + Ki * integral(e) + Kd * de/dt

Two practical additions that every real PID needs:
  * anti-windup  - the integral is clamped, so it cannot grow without limit
                   while the output is saturated;
  * output limit - the result is clipped to [-out_limit, +out_limit].
"""

from __future__ import annotations

from typing import Optional


class PID:
    def __init__(self, kp: float, ki: float = 0.0, kd: float = 0.0,
                 out_limit: Optional[float] = None, i_limit: Optional[float] = None):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_limit = out_limit
        self.i_limit = i_limit
        self.reset()

    def reset(self) -> None:
        self.integral = 0.0
        self.prev_error: Optional[float] = None

    def update(self, error: float, dt: float) -> float:
        """Return the control output for the current error."""
        if dt <= 0:
            raise ValueError("dt must be positive")
        self.integral += error * dt
        if self.i_limit is not None:
            self.integral = max(-self.i_limit, min(self.i_limit, self.integral))
        # First call: no previous error yet, so no derivative kick.
        derivative = 0.0 if self.prev_error is None else (error - self.prev_error) / dt
        self.prev_error = error
        out = self.kp * error + self.ki * self.integral + self.kd * derivative
        if self.out_limit is not None:
            out = max(-self.out_limit, min(self.out_limit, out))
        return out
