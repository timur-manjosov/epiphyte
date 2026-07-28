"""Reaction warmth and bloom intensity's anti-farming properties (Phase 15).

Mirrors test_breadth.py and test_rhythm.py: replays reaction events through the
same pure moisture/structure pipeline bot.py's ``_water_reactor_presence`` and
``_guild_reaction_warmth`` use — decay, per-person diminishing returns, and
``structure.author_breadth`` reused wholesale over reactors instead of message
authors — without touching storage or Discord at all. The self-reaction filter
tested here (``reactor != message_author``) is the same one-line check
``bot.py``'s ``on_raw_reaction_add`` applies before a reaction ever reaches the
presence pipeline.

Design recap (see CLAUDE.md's vitality-signals table and the Phase 15 audit
report for the full note): reaction warmth is sampled once, only on the step a
bloom already earned by Phase 9's maturity/health gate begins, and becomes that
bloom's fixed ``bloom_intensity`` for its whole duration — never a live,
per-tick score. A self-reaction counts for nothing; a small clique trading
reactions with each other is capped at their own distinct headcount, the same
defense ``author_breadth`` already gives message authors against flooding.
"""

import dataclasses
from collections.abc import Sequence

from moisture import decay, next_watering, water
from structure import (
    AUTHOR_PRESENCE_HALF_LIFE_SECONDS,
    BLOOM_HEALTHY_STEPS,
    BLOOM_INTENSITY_FLOOR,
    BLOOM_MIN_NODES,
    BREADTH_SATURATION_VOICES,
    LifeStats,
    author_breadth,
    genome_from_seed,
    germinate,
    grow,
    is_blooming,
    serialize,
)

DAY = 24 * 60 * 60
#: Vitality a lively channel holds — matches test_structure.py's TENDED.
TENDED = 0.75
#: A seed with genes spread across their ranges — matches test_structure.py's
#: TENDED_SEED, reused here for the same reason: a real, non-degenerate genome.
TENDED_SEED = 0x2F3A9C41D77E5B2
#: Stand-in "whoever's message" id for tests where the reacted-to author does
#: not matter, only that it is never equal to a reactor id used in the test.
OTHER_AUTHOR = -1


def _simulate_reactor_warmth(
    events: Sequence[tuple[float, int, int]],
    message_authors: dict[int, int],
    now: float | None = None,
) -> float:
    """Replay reaction ``events`` (sorted ``(timestamp, reactor_id, message_id)``
    triples) and return the guild's reaction-warmth score at ``now`` (defaulting
    to the last event's timestamp).

    A self-reaction (``reactor_id == message_authors[message_id]``) is skipped
    before it touches the presence pipeline at all — exactly what ``bot.py``'s
    ``on_raw_reaction_add`` does with the raw payload's ``message_author_id``,
    so it counts for nothing rather than merely being discounted like an
    ordinary repeat visit within a window.
    """
    windows: dict[int, tuple[float | None, int]] = {}
    presence: dict[int, tuple[float, float]] = {}
    for timestamp, reactor, message_id in events:
        if reactor == message_authors[message_id]:
            continue
        start, count = windows.get(reactor, (None, 0))
        amount, start, count = next_watering(start, count, timestamp)
        windows[reactor] = (start, count)
        weight, last_seen = presence.get(reactor, (0.0, timestamp))
        decayed = decay(weight, timestamp - last_seen, AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
        presence[reactor] = (water(decayed, amount), timestamp)
    end = now if now is not None else events[-1][0]
    weights = [
        decay(weight, end - last_seen, AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
        for weight, last_seen in presence.values()
    ]
    return author_breadth(weights)


def _daily(
    reactor: int, days: int, message_author: int = OTHER_AUTHOR, start: float = 0.0
) -> list[tuple[float, int, int]]:
    """``reactor`` reacting once a day for ``days`` days, all to ``message_author``'s messages."""
    return [(start + day * DAY, reactor, message_author) for day in range(days)]


def _bloom_onset(reaction_warmth: float):
    """Grow a mature, health-banked plant one step into the first bloom it earns.

    Mirrors test_structure.py's ``test_bloom_needs_banked_health_and_a_mature_body``
    recipe exactly: a body already past ``BLOOM_MIN_NODES``, one healthy step
    short of the bank it needs, so the returned structure's single growth step
    is the exact step a bloom begins on — the one step ``reaction_warmth`` is
    ever read on.
    """
    genome = genome_from_seed(TENDED_SEED)
    grown = grow(germinate(TENDED_SEED), genome, TENDED, 400)
    assert len(grown.nodes) >= BLOOM_MIN_NODES, "fixture must be mature enough to bloom"
    poised = dataclasses.replace(grown, stats=LifeStats(healthy_steps=BLOOM_HEALTHY_STEPS - 1))
    return grow(poised, genome, TENDED, 1, reaction_warmth=reaction_warmth)


# --- Self-reactions count for nothing ------------------------------------------


def test_self_reactions_contribute_nothing():
    """A message author reacting to their own message never counts, however often."""
    message_authors = {1: 1}
    self_reaction_events = [(day * DAY, 1, 1) for day in range(60)]
    assert _simulate_reactor_warmth(self_reaction_events, message_authors) == 0.0


def test_self_reactions_do_not_dilute_or_inflate_genuine_warmth():
    """Mixed in with genuine reactions from other people, self-reactions change
    the resulting reading not at all — they are excluded, not merely discounted."""
    message_authors = {1: 1}
    self_reaction_events = [(day * DAY, 1, 1) for day in range(60)]
    genuine_events = [
        (day * DAY, reactor, 1) for reactor in range(2, 8) for day in range(30)
    ]
    mixed = sorted(self_reaction_events + genuine_events)
    now = mixed[-1][0]  # evaluated at the same instant either way

    genuine_only = _simulate_reactor_warmth(genuine_events, message_authors, now=now)
    with_self_reactions_mixed_in = _simulate_reactor_warmth(mixed, message_authors, now=now)
    assert with_self_reactions_mixed_in == genuine_only


# --- The worst-case farming scenario: a small reciprocating clique -------------


def test_small_clique_scores_markedly_lower_than_a_broad_group_at_equal_volume():
    """The worst case this phase has to defend against: 4 accounts trading
    reactions with each other over the entire long window, versus the same raw
    reaction volume spread across a genuinely broad set of people.

    Both groups sustain daily presence well past the ~2-week point that
    registers a voice at all (see test_breadth.py's equivalent check for
    message authors), so this isolates exactly one variable: how many
    *distinct* people the volume came from.
    """
    clique_events = [event for reactor in range(4) for event in _daily(reactor, days=56)]
    broad_events = [event for reactor in range(8) for event in _daily(reactor, days=28)]
    assert len(clique_events) == len(broad_events) == 224  # identical raw volume

    clique_warmth = _simulate_reactor_warmth(clique_events, {OTHER_AUTHOR: OTHER_AUTHOR})
    broad_warmth = _simulate_reactor_warmth(broad_events, {OTHER_AUTHOR: OTHER_AUTHOR})

    assert clique_warmth == 4 / BREADTH_SATURATION_VOICES  # capped at 4 distinct voices
    assert broad_warmth == 1.0  # 8 distinct, sustained voices saturate

    clique_bloom = _bloom_onset(clique_warmth)
    broad_bloom = _bloom_onset(broad_warmth)
    assert clique_bloom.stats.bloom_intensity < broad_bloom.stats.bloom_intensity
    # Not a marginal gap — clearly, provably lower, not just numerically lower.
    assert broad_bloom.stats.bloom_intensity - clique_bloom.stats.bloom_intensity > 0.2


def test_a_solo_reactor_moves_intensity_only_a_little_and_only_after_real_time():
    """One account, reacting only to other people's messages with no reciprocity
    at all, is not literally free manipulation — but it is far less effective
    than genuine broad warmth, and it still costs weeks of real daily presence
    (the same anti-farming curve watering itself uses)."""
    solo_events = _daily(reactor=0, days=56)
    solo_warmth = _simulate_reactor_warmth(solo_events, {OTHER_AUTHOR: OTHER_AUTHOR})
    assert solo_warmth == 1 / BREADTH_SATURATION_VOICES

    quiet_bloom = _bloom_onset(reaction_warmth=0.0)
    solo_bloom = _bloom_onset(reaction_warmth=solo_warmth)
    saturated_bloom = _bloom_onset(reaction_warmth=1.0)

    assert quiet_bloom.stats.bloom_intensity == BLOOM_INTENSITY_FLOOR
    assert solo_bloom.stats.bloom_intensity > quiet_bloom.stats.bloom_intensity  # not zero-cost
    solo_gain = solo_bloom.stats.bloom_intensity - quiet_bloom.stats.bloom_intensity
    broad_gain = saturated_bloom.stats.bloom_intensity - quiet_bloom.stats.bloom_intensity
    assert solo_gain < broad_gain / 2  # far less effective than genuine broad warmth


# --- A healthy but quiet server still blooms, just modestly --------------------


def test_healthy_but_quiet_server_still_blooms_at_the_floor_not_zero():
    """No reaction activity at all never denies a bloom Phase 9's gate already
    earned — it only opens at the floor intensity, still a real bloom."""
    quiet_bloom = _bloom_onset(reaction_warmth=0.0)
    assert is_blooming(quiet_bloom, TENDED)
    assert quiet_bloom.stats.bloom_intensity == BLOOM_INTENSITY_FLOOR
    assert BLOOM_INTENSITY_FLOOR > 0.0


# --- No live, tick-by-tick score to watch and time ------------------------------


def test_bloom_intensity_stays_fixed_for_the_whole_bloom_once_set():
    """Reacting more (or less) once a bloom is already open cannot move its
    intensity — there is no per-step value to watch and time mid-bloom."""
    genome = genome_from_seed(TENDED_SEED)
    onset = _bloom_onset(reaction_warmth=0.0)
    assert onset.stats.in_bloom
    assert onset.stats.bloom_intensity == BLOOM_INTENSITY_FLOOR

    continued = grow(onset, genome, TENDED, 5, reaction_warmth=1.0)
    assert continued.stats.in_bloom
    assert continued.stats.bloom_intensity == BLOOM_INTENSITY_FLOOR


def test_a_new_bloom_reads_reaction_warmth_fresh():
    """Once a bloom ends and a later one is earned, its intensity is sampled
    again from scratch — never carried over from the bloom before it."""
    genome = genome_from_seed(TENDED_SEED)
    first = _bloom_onset(reaction_warmth=1.0)
    assert first.stats.bloom_intensity == 1.0

    spent = grow(first, genome, TENDED, BLOOM_HEALTHY_STEPS + 10, reaction_warmth=1.0)
    assert not is_blooming(spent, TENDED)

    second = grow(spent, genome, TENDED, BLOOM_HEALTHY_STEPS + 10, reaction_warmth=0.0)
    assert second.stats.bloom_count == 2
    assert second.stats.bloom_intensity == BLOOM_INTENSITY_FLOOR


# --- No leakage into growth, branching or moisture ------------------------------


def test_reaction_warmth_never_changes_growth_below_the_bloom_threshold():
    """Below the bloom threshold, reaction_warmth is read every step but used by
    none of them — the grown structure must be byte-identical regardless of it,
    the same non-interference test_rhythm.py and test_breadth.py's own
    modifiers already pass against each other."""
    seed = 5
    genome = genome_from_seed(seed)
    base = germinate(seed)

    quiet = grow(base, genome, 0.9, 300, 0.5, 0.5, 0.0)
    warm = grow(base, genome, 0.9, 300, 0.5, 0.5, 1.0)
    assert serialize(quiet) == serialize(warm)


def test_reaction_warmth_does_not_change_the_moisture_gate():
    """A fully parched plant still only diebacks, regardless of reaction warmth."""
    seed = 5
    genome = genome_from_seed(seed)
    base = germinate(seed)

    parched_quiet = grow(base, genome, 0.0, 20, 0.5, 0.5, 0.0)
    parched_warm = grow(base, genome, 0.0, 20, 0.5, 0.5, 1.0)
    assert serialize(parched_quiet) == serialize(parched_warm)
