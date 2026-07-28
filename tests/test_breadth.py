"""Author breadth's anti-farming property, verified on the pure logic alone.

Mirrors test_farming.py: composes moisture's own decay/water/next_watering with
structure.author_breadth into a simulation of authors messaging over time. It
replays exactly what bot.py's _water_author_presence and _guild_author_breadth
do — decay each author's presence weight to now, top it up with the same
already-anti-farmed watering amount, and count how many authors currently clear
AUTHOR_PRESENCE_FLOOR — without touching storage or Discord at all.
"""

from moisture import decay, next_watering, water
from structure import (
    AUTHOR_PRESENCE_FLOOR,
    AUTHOR_PRESENCE_HALF_LIFE_SECONDS,
    BREADTH_SATURATION_VOICES,
    author_breadth,
)

DAY = 24 * 60 * 60


def _simulate_presence(events: list[tuple[float, int]], now: float | None = None) -> dict[int, float]:
    """Replay watering ``events`` (sorted ``(timestamp, author_id)`` pairs) and
    return each author's presence weight decayed to ``now`` (defaulting to the
    last event's timestamp)."""
    windows: dict[int, tuple[float | None, int]] = {}
    presence: dict[int, tuple[float, float]] = {}
    for timestamp, author in events:
        start, count = windows.get(author, (None, 0))
        amount, start, count = next_watering(start, count, timestamp)
        windows[author] = (start, count)
        weight, last_seen = presence.get(author, (0.0, timestamp))
        decayed = decay(weight, timestamp - last_seen, AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
        presence[author] = (water(decayed, amount), timestamp)
    end = now if now is not None else events[-1][0]
    return {
        author: decay(weight, end - last_seen, AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
        for author, (weight, last_seen) in presence.items()
    }


def _daily(author: int, days: int, per_day: int = 1, start: float = 0.0) -> list[tuple[float, int]]:
    """``author`` sending ``per_day`` messages a day for ``days`` days, from ``start``."""
    step = DAY / per_day
    return [(start + day * DAY + i * step, author) for day in range(days) for i in range(per_day)]


def test_single_day_burst_from_several_fresh_alts_stays_below_the_floor() -> None:
    """A handful of one-off messages from several brand-new accounts today is
    cheap and does not fake a voice: each stays far below the presence floor."""
    events = [(0.0, author) for author in range(6)]
    weights = _simulate_presence(events)
    assert all(weight < AUTHOR_PRESENCE_FLOOR for weight in weights.values())
    assert author_breadth(list(weights.values())) == 0.0


def test_a_single_alt_needs_over_a_week_of_daily_presence_to_register() -> None:
    """One account showing up once a day needs sustained real time, not just a
    few days, before it counts as a genuine voice."""
    short = _simulate_presence(_daily(author=1, days=6, per_day=1))
    assert short[1] < AUTHOR_PRESENCE_FLOOR

    longer = _simulate_presence(_daily(author=1, days=15, per_day=1))
    assert longer[1] >= AUTHOR_PRESENCE_FLOOR


def test_one_flooder_only_ever_counts_as_a_single_voice() -> None:
    """Whatever volume one account sends, it is still exactly one distinct
    author id — breadth cannot mistake a lone flooder for a crowd."""
    events = _daily(author=1, days=30, per_day=500)
    weights = _simulate_presence(events)
    assert len(weights) == 1
    assert author_breadth(list(weights.values())) == 1 / BREADTH_SATURATION_VOICES


def test_sustained_multi_person_activity_saturates_breadth() -> None:
    """Six people, each present daily for three weeks, saturate breadth."""
    events: list[tuple[float, int]] = []
    for author in range(6):
        events += _daily(author, days=21, per_day=1)
    events.sort()
    weights = _simulate_presence(events)
    assert len(weights) == 6
    assert author_breadth(list(weights.values())) == 1.0


def test_small_quiet_server_settles_at_a_stable_partial_score() -> None:
    """Three people chatting daily in a small server settle at a steady,
    intermediate breadth rather than swinging between silence and saturation."""
    scores = []
    for weeks in (2, 3, 4, 6, 8):
        events = []
        for author in range(3):
            events += _daily(author, days=weeks * 7, per_day=1)
        events.sort()
        weights = _simulate_presence(events)
        scores.append(author_breadth(list(weights.values())))

    assert all(0.0 < score < 1.0 for score in scores)
    assert len(set(scores)) == 1  # stable once settled, not oscillating week to week


def test_recently_narrowed_server_reflects_recent_pattern_not_lifetime_history() -> None:
    """A channel that used to have six regular voices but has, for the last
    month, only heard from one of them should see breadth fall accordingly —
    not stay pinned at its months-old high because of who used to be around."""
    crowd_events: list[tuple[float, int]] = []
    for author in range(6):
        crowd_events += _daily(author, days=21, per_day=1)
    crowd_events.sort()
    crowd_weights = _simulate_presence(crowd_events)
    assert author_breadth(list(crowd_weights.values())) == 1.0

    quiet_start = crowd_events[-1][0] + DAY
    quiet_events = crowd_events + _daily(author=0, days=30, per_day=1, start=quiet_start)
    later_weights = _simulate_presence(quiet_events)

    assert author_breadth(list(later_weights.values())) < 1.0
    # the one person who kept posting is still clearly present...
    assert later_weights[0] >= AUTHOR_PRESENCE_FLOOR
    # ...while the five who went quiet a month ago have decayed away.
    assert all(later_weights[author] < AUTHOR_PRESENCE_FLOOR for author in range(1, 6))
