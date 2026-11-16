"""The interface every robot backend implements.

The server only talks to this interface, so the same control and network code
runs on the pure-Python mock (for tests and experiments) and on CoppeliaSim.
"""

from __future__ import annotations

import abc
from typing import List, Tuple


class RobotBackend(abc.ABC):
    #: short name written into every result file ("mock" or "coppeliasim")
    name: str = "base"

    @abc.abstractmethod
    def reset(self) -> None:
        """Put the robot back at its start pose and stop the wheels."""

    @abc.abstractmethod
    def set_wheel_speeds(self, w_left: float, w_right: float) -> None:
        """Command the wheel angular speeds (rad/s)."""

    @abc.abstractmethod
    def step(self, dt: float) -> None:
        """Advance the simulation by dt seconds."""

    @abc.abstractmethod
    def get_pose(self) -> Tuple[float, float, float]:
        """(x, y, theta) in the world frame, metres and radians."""

    @abc.abstractmethod
    def get_sonar(self) -> List[float]:
        """16 sonar distances in metres (max range when nothing is seen)."""

    @abc.abstractmethod
    def get_wheel_speeds(self) -> Tuple[float, float]:
        """Measured (left, right) wheel angular speeds, rad/s."""

    def collisions(self) -> int:
        """Number of collisions so far (only the mock can count them)."""
        return 0

    def close(self) -> None:
        pass
