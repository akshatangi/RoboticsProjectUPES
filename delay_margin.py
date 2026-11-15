"""Delay margin of the teleoperated heading loop.

Heading loop at v = 0: L(s) = K * exp(-s * tau) / (s * (T_m * s + 1)),
where K is the heading gain, T_m the motor lag and tau the total loop delay.
The loop is stable while tau is below the delay margin PM / w_c.
"""

from __future__ import annotations

import math


def _check(k: float, t_m: float) -> None:
    if k <= 0:
        raise ValueError("k must be positive")
    if t_m < 0:
        raise ValueError("t_m must be non-negative")


def crossover_freq(k: float, t_m: float = 0.0) -> float:
    """Gain crossover w_c where |L(j w_c)| = 1 (w_c = k when t_m = 0)."""
    _check(k, t_m)
    s = math.sqrt(1.0 + 4.0 * t_m**2 * k**2)
    return math.sqrt(2.0 * k**2 / (1.0 + s))


def phase_margin(k: float, t_m: float = 0.0) -> float:
    """Phase margin in radians of the delay-free loop."""
    w_c = crossover_freq(k, t_m)
    return math.pi / 2.0 - math.atan(t_m * w_c)


def delay_margin(k: float, t_m: float = 0.0) -> float:
    """Largest total loop delay in seconds that keeps the loop stable (pi / (2 k) when t_m = 0)."""
    return phase_margin(k, t_m) / crossover_freq(k, t_m)


def rtt_margin(k: float, t_m: float = 0.0, t_s: float = 0.0) -> float:
    """Expected critical round-trip time: the delay margin minus half a control period for sampling and hold."""
    return delay_margin(k, t_m) - t_s / 2.0


def k_crit(tau: float, t_m: float = 0.0) -> float:
    """Gain whose delay margin equals tau (pi / (2 tau) when t_m = 0)."""
    if tau <= 0:
        raise ValueError("tau must be positive")
    if t_m < 0:
        raise ValueError("t_m must be non-negative")
    if t_m == 0:
        return math.pi / (2.0 * tau)
    lo, hi = 1e-9, 1.0
    while delay_margin(hi, t_m) > tau:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if delay_margin(mid, t_m) > tau:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)
