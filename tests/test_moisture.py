"""Tests for the pure moisture logic. No Discord involved."""

import pytest

from moisture import (
    DEFAULT_HALF_LIFE_SECONDS,
    DEFAULT_WATER_AMOUNT,
    DRY_MAX,
    HEALTHY_MAX,
    MAX_MOISTURE,
    MIN_MOISTURE,
    WATERING_FALLOFF,
    WATERING_WINDOW_SECONDS,
    WITHERED_MAX,
    Stage,
    decay,
    effective_water_amount,
    next_watering,
    stage,
    water,
)


def test_decay_is_strictly_decreasing() -> None:
    """For a positive start, longer elapsed time yields strictly less moisture."""
    previous = 1.0
    for hours in range(1, 25):
        current = decay(1.0, hours * 3600, DEFAULT_HALF_LIFE_SECONDS)
        assert current < previous
        previous = current


def test_decay_halves_after_one_half_life() -> None:
    """After exactly one half-life the moisture is halved."""
    assert decay(1.0, DEFAULT_HALF_LIFE_SECONDS, DEFAULT_HALF_LIFE_SECONDS) == pytest.approx(0.5)


def test_decay_approaches_zero() -> None:
    """After many half-lives the moisture is arbitrarily close to zero."""
    result = decay(1.0, DEFAULT_HALF_LIFE_SECONDS * 60, DEFAULT_HALF_LIFE_SECONDS)
    assert 0.0 <= result < 1e-9


def test_decay_zero_elapsed_is_identity() -> None:
    """With no elapsed time the moisture is unchanged."""
    assert decay(0.8, 0.0) == pytest.approx(0.8)


def test_decay_stays_within_range() -> None:
    """Decay never leaves the valid interval for any input."""
    for moisture in (0.0, 0.3, 1.0):
        for elapsed in (0, 100, 10_000, 1_000_000):
            result = decay(moisture, elapsed)
            assert MIN_MOISTURE <= result <= MAX_MOISTURE


def test_water_caps_at_one() -> None:
    """Watering never pushes moisture above 1.0."""
    assert water(0.95, 0.2) == pytest.approx(MAX_MOISTURE)
    assert water(1.0, 0.5) == pytest.approx(MAX_MOISTURE)


def test_water_never_below_zero() -> None:
    """Even from a nonsensical negative start, the result stays at or above 0.0."""
    assert water(-0.5, 0.1) >= MIN_MOISTURE


def test_water_increases_moisture() -> None:
    """Watering raises moisture by the given amount within range."""
    assert water(0.2, 0.15) == pytest.approx(0.35)


def test_stage_boundaries() -> None:
    """Stage boundaries map to the expected named stages."""
    assert stage(MIN_MOISTURE) is Stage.WITHERED
    assert stage(WITHERED_MAX - 0.001) is Stage.WITHERED
    assert stage(WITHERED_MAX) is Stage.DRY
    assert stage(DRY_MAX - 0.001) is Stage.DRY
    assert stage(DRY_MAX) is Stage.HEALTHY
    assert stage(HEALTHY_MAX - 0.001) is Stage.HEALTHY
    assert stage(HEALTHY_MAX) is Stage.THRIVING
    assert stage(MAX_MOISTURE) is Stage.THRIVING


def test_effective_water_amount_first_is_base() -> None:
    """The first watering in a window delivers the full base amount."""
    assert effective_water_amount(0) == pytest.approx(DEFAULT_WATER_AMOUNT)


def test_effective_water_amount_strictly_decreasing() -> None:
    """Each further watering within a window adds strictly less."""
    amounts = [effective_water_amount(k) for k in range(8)]
    assert all(later < earlier for earlier, later in zip(amounts, amounts[1:]))


def test_effective_water_amount_bounded_sum() -> None:
    """A single person's total per window stays at or below the geometric bound."""
    bound = DEFAULT_WATER_AMOUNT / (1 - WATERING_FALLOFF)
    total = sum(effective_water_amount(k) for k in range(1000))
    assert total <= bound
    assert total == pytest.approx(bound)  # and it approaches it


def test_next_watering_first_time() -> None:
    """With no prior window, the window opens now and the full amount is added."""
    amount, start, count = next_watering(None, 0, now=1000.0)
    assert amount == pytest.approx(DEFAULT_WATER_AMOUNT)
    assert start == 1000.0
    assert count == 1


def test_next_watering_diminishes_within_window() -> None:
    """Consecutive waterings inside the window add progressively less."""
    amount1, start, count = next_watering(None, 0, now=0.0)
    amount2, start, count = next_watering(start, count, now=10.0)
    amount3, start, count = next_watering(start, count, now=20.0)
    assert amount1 > amount2 > amount3
    assert start == 0.0  # window did not reset
    assert count == 3


def test_next_watering_resets_after_window() -> None:
    """Once the window has fully elapsed, the amount resets to base."""
    _, start, count = next_watering(None, 0, now=0.0)
    _, start, count = next_watering(start, count, now=1.0)  # discounted
    amount, start, count = next_watering(start, count, now=WATERING_WINDOW_SECONDS + 1)
    assert amount == pytest.approx(DEFAULT_WATER_AMOUNT)
    assert start == WATERING_WINDOW_SECONDS + 1
    assert count == 1
