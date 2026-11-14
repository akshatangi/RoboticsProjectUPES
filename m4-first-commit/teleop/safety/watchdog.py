"""Heartbeat watchdogs for the robot side. Sans-IO: time is always passed in by the caller.

A watchdog is armed by its first heartbeat. After that it trips when the time since the last
heartbeat arrival is strictly greater than its timeout.
"""

from __future__ import annotations


class FixedWatchdog:
    def __init__(self, timeout_ms: float) -> None:
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self._timeout_ms = float(timeout_ms)
        self._last_ms: float | None = None

    @property
    def timeout_ms(self) -> float:
        return self._timeout_ms

    @property
    def armed(self) -> bool:
        return self._last_ms is not None

    def on_heartbeat(self, now_ms: float) -> None:
        if self._last_ms is not None and now_ms < self._last_ms:
            raise ValueError("time went backwards")
        self._last_ms = float(now_ms)

    def tripped(self, now_ms: float) -> bool:
        return self._last_ms is not None and now_ms - self._last_ms > self._timeout_ms

    def reset(self) -> None:
        self._last_ms = None


class AdaptiveWatchdog:
    """Timeout = mean gap + k * gap deviation, clamped to [t_min, t_max].

    Gaps between heartbeat arrivals are used instead of the RTT level: a constant delay shifts
    every arrival equally and leaves the gaps unchanged, while jitter and loss change them.
    """

    def __init__(
        self,
        hb_period_ms: float,
        alpha: float = 1 / 8,
        beta: float = 1 / 4,
        k: float = 4.0,
        t_min_factor: float = 2.0,
        t_max_ms: float = 3000.0,
    ) -> None:
        if hb_period_ms <= 0:
            raise ValueError("hb_period_ms must be positive")
        self.hb_period_ms = float(hb_period_ms)
        self.alpha = alpha
        self.beta = beta
        self.k = k
        self._t_min_ms = t_min_factor * self.hb_period_ms
        self._t_max_ms = float(t_max_ms)
        if self._t_min_ms > self._t_max_ms:
            raise ValueError("t_min exceeds t_max")
        self.reset()

    def reset(self) -> None:
        self._last_ms: float | None = None
        self._mean_ms = self.hb_period_ms
        self._dev_ms = self.hb_period_ms / 2

    @property
    def armed(self) -> bool:
        return self._last_ms is not None

    @property
    def timeout_ms(self) -> float:
        raw = self._mean_ms + self.k * self._dev_ms
        return min(max(raw, self._t_min_ms), self._t_max_ms)

    def on_heartbeat(self, now_ms: float) -> None:
        if self._last_ms is not None:
            if now_ms < self._last_ms:
                raise ValueError("time went backwards")
            gap = now_ms - self._last_ms
            self._dev_ms = (1 - self.beta) * self._dev_ms + self.beta * abs(self._mean_ms - gap)
            self._mean_ms = (1 - self.alpha) * self._mean_ms + self.alpha * gap
        self._last_ms = float(now_ms)

    def tripped(self, now_ms: float) -> bool:
        return self._last_ms is not None and now_ms - self._last_ms > self.timeout_ms
