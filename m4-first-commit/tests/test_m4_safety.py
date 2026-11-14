import random

import pytest

from teleop.safety import (
    AdaptiveWatchdog,
    FixedWatchdog,
    RttEstimator,
    load_safety_config,
    make_adaptive_watchdog,
    make_fixed_watchdogs,
    make_rtt_estimator,
)


def test_rtt_first_sample():
    e = RttEstimator()
    assert not e.has_sample
    e.update(100.0)
    assert e.srtt_ms == 100.0
    assert e.rttvar_ms == 50.0


def test_rtt_second_sample_matches_rfc6298_rule():
    e = RttEstimator()
    e.update(100.0)
    e.update(200.0)
    assert e.rttvar_ms == pytest.approx(0.75 * 50.0 + 0.25 * 100.0)
    assert e.srtt_ms == pytest.approx(0.875 * 100.0 + 0.125 * 200.0)


def test_rtt_constant_samples_drive_variance_to_zero():
    e = RttEstimator()
    for _ in range(200):
        e.update(80.0)
    assert e.srtt_ms == pytest.approx(80.0)
    assert e.rttvar_ms == pytest.approx(0.0, abs=1e-6)


def test_rtt_rejects_negative_and_resets():
    e = RttEstimator()
    with pytest.raises(ValueError):
        e.update(-1.0)
    e.update(10.0)
    e.reset()
    assert not e.has_sample


def test_fixed_not_armed_until_first_heartbeat():
    w = FixedWatchdog(400)
    assert not w.armed
    assert not w.tripped(10_000)
    w.on_heartbeat(0)
    assert w.armed


def test_fixed_trip_boundary_is_strict():
    w = FixedWatchdog(400)
    w.on_heartbeat(1000)
    assert not w.tripped(1400)
    assert w.tripped(1401)


def test_fixed_heartbeat_resets_timer_and_reset_disarms():
    w = FixedWatchdog(400)
    w.on_heartbeat(0)
    w.on_heartbeat(300)
    assert not w.tripped(600)
    w.reset()
    assert not w.armed


def test_fixed_rejects_bad_input():
    with pytest.raises(ValueError):
        FixedWatchdog(0)
    w = FixedWatchdog(400)
    w.on_heartbeat(100)
    with pytest.raises(ValueError):
        w.on_heartbeat(50)


def test_adaptive_initial_timeout():
    w = AdaptiveWatchdog(200)
    assert w.timeout_ms == pytest.approx(600.0)


def test_adaptive_steady_gaps_shrink_timeout_to_minimum():
    w = AdaptiveWatchdog(200)
    for i in range(200):
        w.on_heartbeat(i * 200)
    assert w.timeout_ms == pytest.approx(400.0)


def test_adaptive_large_gap_hits_maximum():
    w = AdaptiveWatchdog(200)
    w.on_heartbeat(0)
    w.on_heartbeat(5000)
    assert w.timeout_ms == 3000.0


def test_adaptive_jitter_raises_timeout():
    w = AdaptiveWatchdog(200)
    t = 0.0
    w.on_heartbeat(t)
    for i in range(200):
        t += 100 if i % 2 == 0 else 300
        w.on_heartbeat(t)
    assert w.timeout_ms > 450.0


def test_adaptive_no_false_trip_with_bounded_jitter():
    rng = random.Random(0)
    w = AdaptiveWatchdog(200)
    t = 0.0
    w.on_heartbeat(t)
    for _ in range(600):
        gap = rng.uniform(150, 250)
        assert not w.tripped(t + gap)
        t += gap
        w.on_heartbeat(t)


def test_adaptive_detects_link_loss_sooner_than_fixed_800():
    adaptive = AdaptiveWatchdog(200)
    fixed = FixedWatchdog(800)
    last = 0.0
    for i in range(100):
        last = i * 200.0
        adaptive.on_heartbeat(last)
        fixed.on_heartbeat(last)

    def trip_time(w):
        t = last
        while not w.tripped(t):
            t += 1
        return t - last

    assert trip_time(adaptive) < trip_time(fixed)
    assert trip_time(adaptive) == pytest.approx(401, abs=1)


def test_adaptive_rejects_bad_input():
    with pytest.raises(ValueError):
        AdaptiveWatchdog(0)
    with pytest.raises(ValueError):
        AdaptiveWatchdog(200, t_max_ms=100)


def test_config_loads_and_builds_objects():
    cfg = load_safety_config()
    assert cfg.fixed_timeouts_ms == (400.0, 800.0, 1600.0)
    assert make_rtt_estimator(cfg).alpha == 0.125
    wd = make_adaptive_watchdog(cfg, 200)
    assert wd.timeout_ms == pytest.approx(600.0)
    assert [w.timeout_ms for w in make_fixed_watchdogs(cfg)] == [400.0, 800.0, 1600.0]
