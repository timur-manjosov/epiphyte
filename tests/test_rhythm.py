"""Temporal rhythm's anti-farming property, verified on the pure logic alone.

Mirrors test_breadth.py: exercises structure.temporal_rhythm() directly with
hand-built daily-count windows, the same shape bot.py's _guild_rhythm builds
from the daily_activity table — without touching storage or Discord at all.
"""

from structure import (
    NEUTRAL_RHYTHM,
    RHYTHM_MIN_ACTIVE_DAYS,
    RHYTHM_WINDOW_DAYS,
    day_bucket,
    temporal_rhythm,
)

DAY = 24 * 60 * 60


def _steady(per_day: int, days: int = RHYTHM_WINDOW_DAYS) -> list[int]:
    """``per_day`` messages every day for ``days`` days: perfectly even."""
    return [per_day] * days


def _bursty(per_active_day: int, active_days: int, days: int = RHYTHM_WINDOW_DAYS) -> list[int]:
    """The same volume concentrated into ``active_days`` days, silent the rest."""
    return [per_active_day] * active_days + [0] * (days - active_days)


def test_day_bucket_groups_timestamps_by_whole_utc_day() -> None:
    start = 10 * DAY
    assert day_bucket(start) == day_bucket(start + DAY - 1)
    assert day_bucket(start) != day_bucket(start + DAY)


def test_short_or_sparse_history_defaults_to_neutral() -> None:
    """Too few active days in the window — a young server, or a server too quiet
    to have a real pattern yet — is not enough signal to trust, so this stays at
    the neutral default rather than reading as an extreme in either direction."""
    just_under_the_threshold = [5] * (RHYTHM_MIN_ACTIVE_DAYS - 1) + [0] * (
        RHYTHM_WINDOW_DAYS - (RHYTHM_MIN_ACTIVE_DAYS - 1)
    )
    assert temporal_rhythm(just_under_the_threshold) == NEUTRAL_RHYTHM
    assert temporal_rhythm([0] * RHYTHM_WINDOW_DAYS) == NEUTRAL_RHYTHM
    assert temporal_rhythm([]) == NEUTRAL_RHYTHM


def test_steady_daily_activity_scores_maximally_regular() -> None:
    assert temporal_rhythm(_steady(10)) == 1.0
    assert temporal_rhythm(_steady(1)) == 1.0  # volume doesn't matter, only shape


def test_bursty_activity_scores_low_regularity_despite_equal_total_activity() -> None:
    """The exact same total messages as the steady case (560 over the window),
    concentrated into just enough days to clear the trust threshold instead of
    spread over all 56 — this should score clearly, not just marginally, lower."""
    steady_total = 10 * RHYTHM_WINDOW_DAYS
    bursty = _bursty(steady_total // RHYTHM_MIN_ACTIVE_DAYS, RHYTHM_MIN_ACTIVE_DAYS)

    steady_score = temporal_rhythm(_steady(10))
    bursty_score = temporal_rhythm(bursty)

    assert steady_score == 1.0
    assert bursty_score < 0.3
    assert steady_score - bursty_score > 0.5


def test_burst_volume_cannot_buy_regularity() -> None:
    """Scale invariance is what makes this un-farmable: flooding the same handful
    of days with ten, or a thousand, times the messages produces the exact same
    score — no message count turns a burst into 'steady'. This is the concrete
    check behind the admission test's third criterion: a single actor (or a
    coordinated group) cannot spam their way to a high rhythm reading."""
    modest = temporal_rhythm(_bursty(5, RHYTHM_MIN_ACTIVE_DAYS))
    heavy = temporal_rhythm(_bursty(500, RHYTHM_MIN_ACTIVE_DAYS))
    extreme = temporal_rhythm(_bursty(50_000, RHYTHM_MIN_ACTIVE_DAYS))
    assert modest == heavy == extreme
    assert modest < 0.3  # and it never reads as steady, whatever the volume


def test_extreme_single_day_burst_falls_back_to_neutral_not_high() -> None:
    """All activity on a single day, everything else silent, has too few active
    days to trust (see RHYTHM_MIN_ACTIVE_DAYS) — it lands on the neutral default,
    not on a high 'steady' score. Either outcome is safe for the admission test:
    what must never happen is a burst reading as regular, and it doesn't."""
    single_day_mega_burst = _bursty(1_000_000, 1)
    assert temporal_rhythm(single_day_mega_burst) == NEUTRAL_RHYTHM


def test_more_active_days_at_the_same_total_reads_as_more_regular() -> None:
    """Spreading the same total activity over more distinct days — the genuine
    lever a community actually controls, unlike raw volume (see
    test_burst_volume_cannot_buy_regularity) — visibly raises the score."""
    total = 600
    concentrated = temporal_rhythm(_bursty(total // RHYTHM_MIN_ACTIVE_DAYS, RHYTHM_MIN_ACTIVE_DAYS))
    spread = temporal_rhythm(_bursty(total // 30, 30))
    assert spread > concentrated
