"""Round-trip-time estimation from heartbeat echoes, following the RFC 6298 update rules."""

from __future__ import annotations


class RttEstimator:
    def __init__(self, alpha: float = 1 / 8, beta: float = 1 / 4) -> None:
        self.alpha = alpha
        self.beta = beta
        self.srtt_ms: float | None = None
        self.rttvar_ms: float | None = None

    @property
    def has_sample(self) -> bool:
        return self.srtt_ms is not None

    def update(self, sample_ms: float) -> None:
        if sample_ms < 0:
            raise ValueError("RTT sample must be non-negative")
        if self.srtt_ms is None or self.rttvar_ms is None:
            self.srtt_ms = float(sample_ms)
            self.rttvar_ms = sample_ms / 2
            return
        self.rttvar_ms = (1 - self.beta) * self.rttvar_ms + self.beta * abs(self.srtt_ms - sample_ms)
        self.srtt_ms = (1 - self.alpha) * self.srtt_ms + self.alpha * sample_ms

    def reset(self) -> None:
        self.srtt_ms = None
        self.rttvar_ms = None
