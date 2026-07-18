"""Pure moisture logic for Epiphyte.

No side effects, no clock reads, no ``import discord``. Given the same inputs
these functions always return the same outputs, which makes them testable with
pytest without ever starting Discord.

Moisture is a float in the closed interval ``[0.0, 1.0]``: ``0.0`` means the
plant is dead, ``1.0`` means it is fully watered.

The constants are calibrated to a daily timescale: the plant withers over days
of silence, not minutes, and the anti-farming curve bounds how much any single
person can contribute within a window (see ``effective_water_amount``).
"""

from __future__ import annotations

from enum import Enum

#: Lowest possible moisture value (dead).
MIN_MOISTURE: float = 0.0
#: Highest possible moisture value (fully watered).
MAX_MOISTURE: float = 1.0

#: Time after which moisture halves through decay. One day: a plant left in
#: silence falls from thriving to withered over roughly three days.
DEFAULT_HALF_LIFE_SECONDS: float = 24 * 60 * 60  # 1 day
#: Moisture added by a person's first watering within their window. Sized so a
#: single person's capped contribution settles the plant in the withered band,
#: while several people together lift it into healthy territory.
DEFAULT_WATER_AMOUNT: float = 0.05
#: Length of the per-person diminishing-returns window.
WATERING_WINDOW_SECONDS: float = 24 * 60 * 60  # 1 day
#: Factor discounting each further watering by the same person within a window.
#: With 0.5 the geometric series caps one person's per-window contribution at
#: ``DEFAULT_WATER_AMOUNT / (1 - 0.5)`` no matter how many messages they send.
WATERING_FALLOFF: float = 0.5

#: Upper bound (exclusive) of the WITHERED range.
WITHERED_MAX: float = 0.15
#: Upper bound (exclusive) of the DRY range.
DRY_MAX: float = 0.40
#: Upper bound (exclusive) of the HEALTHY range.
HEALTHY_MAX: float = 0.75


class Stage(Enum):
    """Named moisture stages, ordered from driest to lushest."""

    WITHERED = "withered"
    DRY = "dry"
    HEALTHY = "healthy"
    THRIVING = "thriving"


def _clamp(value: float) -> float:
    """Clamp ``value`` into the valid moisture interval ``[0.0, 1.0]``."""
    return max(MIN_MOISTURE, min(MAX_MOISTURE, value))


def decay(
    moisture: float,
    elapsed_seconds: float,
    half_life_seconds: float = DEFAULT_HALF_LIFE_SECONDS,
) -> float:
    """Return ``moisture`` after exponential decay over ``elapsed_seconds``.

    The function never reads a clock; the elapsed time is passed in. Moisture
    halves every ``half_life_seconds`` and asymptotically approaches ``0.0``
    without ever going negative. For a positive starting moisture the result is
    strictly decreasing in ``elapsed_seconds``.
    """
    elapsed = max(0.0, elapsed_seconds)
    factor = 0.5 ** (elapsed / half_life_seconds)
    return _clamp(moisture * factor)


def water(moisture: float, amount: float = DEFAULT_WATER_AMOUNT) -> float:
    """Return ``moisture`` increased by ``amount``, capped at ``1.0``.

    The result never leaves the valid interval ``[0.0, 1.0]``.
    """
    return _clamp(moisture + amount)


def stage(moisture: float) -> Stage:
    """Map a moisture value to its named growth stage.

    Ranges are half-open: ``WITHERED`` is ``[0, 0.15)``, ``DRY`` is
    ``[0.15, 0.40)``, ``HEALTHY`` is ``[0.40, 0.75)`` and ``THRIVING`` is
    ``[0.75, 1.0]``.
    """
    value = _clamp(moisture)
    if value < WITHERED_MAX:
        return Stage.WITHERED
    if value < DRY_MAX:
        return Stage.DRY
    if value < HEALTHY_MAX:
        return Stage.HEALTHY
    return Stage.THRIVING


def effective_water_amount(
    prior_waterings: int,
    base_amount: float = DEFAULT_WATER_AMOUNT,
    falloff: float = WATERING_FALLOFF,
) -> float:
    """Return the moisture a watering adds under diminishing returns.

    ``prior_waterings`` is how many times the same person already watered within
    the current window. The amount is ``base_amount * falloff ** prior_waterings``,
    so it is strictly decreasing and its running sum stays below
    ``base_amount / (1 - falloff)``. That bound is the anti-farming lever: a
    single person's total contribution per window is capped no matter how many
    messages they send, while several people each add their own share.
    """
    return base_amount * (falloff ** prior_waterings)


def next_watering(
    window_start: float | None,
    count_in_window: int,
    now: float,
    base_amount: float = DEFAULT_WATER_AMOUNT,
    window_seconds: float = WATERING_WINDOW_SECONDS,
    falloff: float = WATERING_FALLOFF,
) -> tuple[float, float, int]:
    """Resolve one watering against a person's diminishing-returns window.

    Given the person's current window start and how many times they have watered
    in it, plus the current time ``now``, return ``(amount, new_window_start,
    new_count)``. If no window exists yet or the previous one has fully elapsed,
    the window resets and this watering delivers the full ``base_amount``;
    otherwise it is discounted per :func:`effective_water_amount`. Pure — the
    caller supplies ``now`` and stores the returned window state.
    """
    if window_start is None or now - window_start >= window_seconds:
        window_start = now
        count_in_window = 0
    amount = effective_water_amount(count_in_window, base_amount, falloff)
    return amount, window_start, count_in_window + 1
