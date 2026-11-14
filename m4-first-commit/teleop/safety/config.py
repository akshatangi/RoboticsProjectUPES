"""Loading the safety constants from config/safety.yaml and building safety objects from them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from teleop.safety.rtt import RttEstimator
from teleop.safety.watchdog import AdaptiveWatchdog, FixedWatchdog

DEFAULT_SAFETY_PATH = Path(__file__).resolve().parents[2] / "config" / "safety.yaml"


@dataclass(frozen=True)
class SafetyConfig:
    rtt_alpha: float
    rtt_beta: float
    wd_alpha: float
    wd_beta: float
    wd_k: float
    wd_t_min_factor: float
    wd_t_max_ms: float
    fixed_timeouts_ms: tuple[float, ...]


def load_safety_config(path: Path | str = DEFAULT_SAFETY_PATH) -> SafetyConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return SafetyConfig(
        rtt_alpha=float(raw["rtt"]["alpha"]),
        rtt_beta=float(raw["rtt"]["beta"]),
        wd_alpha=float(raw["adaptive_watchdog"]["alpha"]),
        wd_beta=float(raw["adaptive_watchdog"]["beta"]),
        wd_k=float(raw["adaptive_watchdog"]["k"]),
        wd_t_min_factor=float(raw["adaptive_watchdog"]["t_min_factor"]),
        wd_t_max_ms=float(raw["adaptive_watchdog"]["t_max_ms"]),
        fixed_timeouts_ms=tuple(float(t) for t in raw["fixed_watchdog_timeouts_ms"]),
    )


def make_rtt_estimator(cfg: SafetyConfig) -> RttEstimator:
    return RttEstimator(alpha=cfg.rtt_alpha, beta=cfg.rtt_beta)


def make_adaptive_watchdog(cfg: SafetyConfig, hb_period_ms: float) -> AdaptiveWatchdog:
    return AdaptiveWatchdog(
        hb_period_ms,
        alpha=cfg.wd_alpha,
        beta=cfg.wd_beta,
        k=cfg.wd_k,
        t_min_factor=cfg.wd_t_min_factor,
        t_max_ms=cfg.wd_t_max_ms,
    )


def make_fixed_watchdogs(cfg: SafetyConfig) -> list[FixedWatchdog]:
    return [FixedWatchdog(t) for t in cfg.fixed_timeouts_ms]
