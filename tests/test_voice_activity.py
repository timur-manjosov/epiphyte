"""Voice activity's qualification, anti-farming and independence properties (Phase 17).

Mirrors test_breadth.py, test_rhythm.py, test_reactions.py and test_threads.py:
replays voice sessions through the same pure moisture/structure pipeline
``bot.py``'s ``_settle_voice_channel``, ``_credit_voice_seconds``,
``_water_voice_presence`` and ``_voice_activity`` use — the shared-audible-time
rule, the 15-minute credit, the per-person diminishing-returns window, the
week-long presence decay and ``structure.author_breadth`` reused wholesale over
voice participants — without touching storage or Discord at all.

Design recap (see CLAUDE.md's vitality-signals table and the Phase 17 audit
report): voice activity is the only signal that reaches no part of ``grow()``.
It drives the root system and the trunk's basal flare in ``render.py`` instead,
which is what makes it independent of author breadth, temporal rhythm and thread
depth *by construction* — there is no shared term for them to interact through —
rather than by the empirical corner-testing the three growth modifiers needed
against each other. Time only counts while at least VOICE_MIN_AUDIBLE people are
audible in the same channel, so a lone occupant earns nothing however long they
stay, and the visible effect is deliberately confined to the top of the range by
``root_spread``'s threshold and curve.

The last section is the one place in this suite that imports ``render``. Two of
this phase's load-bearing claims are properties of the drawing itself and cannot
be stated in pure logic: that "no voice activity" is byte-identical to the
pre-Phase-17 image rather than merely calibrated to look like it, and that
"subtle" is an actual measured bound on how much of the frame moves rather than
an adjective. Everything else here stays pure.
"""

import inspect
from collections.abc import Sequence
from itertools import pairwise

from PIL import Image

# render/Pillow are imported for the final section only — see the module
# docstring for why those two claims cannot be stated in pure logic.
import render
from moisture import decay, next_watering, water
from structure import (
    AUTHOR_PRESENCE_HALF_LIFE_SECONDS,
    BREADTH_SATURATION_VOICES,
    VOICE_CREDIT_SECONDS,
    VOICE_MIN_AUDIBLE,
    VOICE_ROOT_THRESHOLD,
    author_breadth,
    genome_from_seed,
    germinate,
    grow,
    root_spread,
    shared_voice_seconds,
    voice_credits,
    voice_is_audible,
)

DAY = 24 * 60 * 60
HOUR = 60 * 60
#: Vitality a lively channel holds — matches test_structure.py's TENDED.
TENDED = 0.75
#: A seed with genes spread across their ranges — matches test_structure.py's
#: TENDED_SEED, reused here for the same reason: a real, non-degenerate genome.
TENDED_SEED = 0x2F3A9C41D77E5B2


# --- What counts as being genuinely in the room --------------------------------


def test_someone_present_and_unmuted_counts():
    assert voice_is_audible(connected=True, muted=False, deafened=False, in_afk_channel=False)


def test_idling_in_voice_counts_for_nothing():
    """The three ways of being connected without taking part — muted, deafened,
    or parked in the guild's AFK channel — all read exactly like not being
    connected at all. Idling in a voice channel is the cheapest imaginable way
    to fake this signal, so it has to be worth precisely zero, not a discount."""
    assert not voice_is_audible(connected=False, muted=False, deafened=False, in_afk_channel=False)
    assert not voice_is_audible(connected=True, muted=True, deafened=False, in_afk_channel=False)
    assert not voice_is_audible(connected=True, muted=False, deafened=True, in_afk_channel=False)
    assert not voice_is_audible(connected=True, muted=False, deafened=False, in_afk_channel=True)


def test_a_lone_occupant_accrues_nothing_however_long_they_stay():
    """The distinct-presence requirement, stated at its starkest: one person
    audible in a voice channel for a solid week earns zero seconds. This is a
    stricter defence than the text signals can manage — there the anti-farming
    is a *cap* on one person's amount, here the requirement is simultaneity,
    which one account cannot manufacture at all."""
    assert shared_voice_seconds(1, 7 * DAY) == 0.0
    assert shared_voice_seconds(0, 7 * DAY) == 0.0


def test_shared_time_counts_from_the_minimum_headcount_upward():
    assert shared_voice_seconds(VOICE_MIN_AUDIBLE, HOUR) == HOUR
    assert shared_voice_seconds(VOICE_MIN_AUDIBLE - 1, HOUR) == 0.0
    # A bigger room is not worth more per second — headcount is a gate here, and
    # breadth over distinct people is what the presence weights measure later.
    assert shared_voice_seconds(9, HOUR) == shared_voice_seconds(2, HOUR)


def test_credits_carry_their_remainder_forward():
    """Several short calls across an evening are worth exactly what one unbroken
    call of the same total length is — the model must not quietly reward sitting
    in a channel over the stop-start shape real conversation actually has."""
    assert voice_credits(VOICE_CREDIT_SECONDS - 1) == (0, VOICE_CREDIT_SECONDS - 1)
    assert voice_credits(VOICE_CREDIT_SECONDS) == (1, 0.0)

    unbroken, _ = voice_credits(4 * VOICE_CREDIT_SECONDS)
    banked = 0.0
    piecemeal = 0
    for _ in range(8):
        earned, banked = voice_credits(banked + VOICE_CREDIT_SECONDS / 2)
        piecemeal += earned
    assert piecemeal == unbroken == 4


# --- The root-spread curve: what "subtle" concretely means ----------------------


def test_no_voice_usage_is_an_abstention_not_a_penalty():
    """Most servers never use voice channels at all. That has to read as exactly
    the pre-Phase-17 plant — not a small effect, none — the same way
    NEUTRAL_THREAD_DEPTH treats never having used threads."""
    assert root_spread(0.0) == 0.0


def test_a_daily_calling_duo_is_still_invisible():
    """Two people who call each other every day are not what "this server has a
    hidden life in voice" means, and the threshold is placed so they read as
    exactly nothing: two of BREADTH_SATURATION_VOICES is below it."""
    assert root_spread(2 / BREADTH_SATURATION_VOICES) == 0.0
    assert root_spread(VOICE_ROOT_THRESHOLD) == 0.0


def test_the_curve_starts_almost_imperceptibly_and_only_opens_up_near_saturation():
    """The whole design of this dimension is in the shape of this curve: past the
    threshold it must not fade in linearly, or a merely-above-average server gets
    a clearly drawn root system. Four sustained voices are worth about a tenth of
    the full effect, five about four tenths, and only six the whole of it."""
    four, five, six = (root_spread(n / BREADTH_SATURATION_VOICES) for n in (4, 5, 6))
    assert 0.0 < four < 0.15
    assert 0.3 < five < 0.5
    assert six == 1.0
    # Concave-up, not linear: each further voice is worth more than the last.
    assert (five - four) > (four - 0.0)
    assert (six - five) > (five - four)


def test_root_spread_is_monotone_and_bounded():
    scores = [root_spread(i / 40) for i in range(41)]
    assert all(b >= a for a, b in pairwise(scores))
    assert scores[0] == 0.0 and scores[-1] == 1.0
    assert root_spread(-5.0) == 0.0 and root_spread(5.0) == 1.0  # clamped, never extrapolated


# --- Anti-farming: replaying real sessions through the whole pipeline -----------


def _simulate_voice_activity(
    sessions: Sequence[tuple[float, Sequence[int], float]], now: float | None = None
) -> float:
    """Replay voice ``sessions`` — ``(start_timestamp, participants, seconds)``
    triples, each a stretch during which exactly those people were audible
    together in one channel — and return the guild's voice-activity reading at
    ``now`` (defaulting to the last session's start).

    This is precisely the chain ``bot.py`` runs: shared time is judged by
    :func:`shared_voice_seconds`, banked per person into whole
    :func:`voice_credits`, each credit put through that person's own
    diminishing-returns window (:func:`moisture.next_watering`), topped into a
    presence weight that decays on the week-long author-presence half-life, and
    finally read by :func:`author_breadth` over the distinct people who cleared
    the floor.
    """
    windows: dict[int, tuple[float | None, int]] = {}
    presence: dict[int, tuple[float, float]] = {}
    banked: dict[int, float] = {}
    for timestamp, participants, seconds in sessions:
        credited = shared_voice_seconds(len(participants), seconds)
        for person in participants:
            credits, banked[person] = voice_credits(banked.get(person, 0.0) + credited)
            for _ in range(credits):
                start, count = windows.get(person, (None, 0))
                amount, start, count = next_watering(start, count, timestamp)
                windows[person] = (start, count)
                weight, last_seen = presence.get(person, (0.0, timestamp))
                decayed = decay(weight, timestamp - last_seen, AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
                presence[person] = (water(decayed, amount), timestamp)
    end = now if now is not None else sessions[-1][0]
    weights = [
        decay(weight, end - last_seen, AUTHOR_PRESENCE_HALF_LIFE_SECONDS)
        for weight, last_seen in presence.values()
    ]
    return author_breadth(weights)


def _daily(participants: Sequence[int], days: int, seconds: float) -> list:
    """``participants`` audible together for ``seconds`` once a day, for ``days`` days."""
    return [(day * DAY, participants, seconds) for day in range(days)]


def test_one_person_camping_in_voice_for_a_month_moves_nothing_at_all():
    """The headline attack, run to its extreme: someone sits alone in a voice
    channel eight hours a day for a month, unmuted the whole time. Not a reduced
    effect — literally no presence weight is ever created, so the reading is zero
    and the root system stays exactly as absent as a server that has no voice
    channels."""
    activity = _simulate_voice_activity(_daily([1], days=30, seconds=8 * HOUR))
    assert activity == 0.0
    assert root_spread(activity) == 0.0


def test_two_accounts_farming_together_are_capped_at_their_own_headcount():
    """The obvious next attack: one person runs a second account and parks both
    in a channel so the simultaneity gate is satisfied. They earn genuine
    presence — there is no way to tell two accounts from two people without
    privileged intents — but only ever *two* distinct voices' worth of it, which
    the threshold places firmly below anything visible. The same anti-clique
    property author_breadth already gives message authors against flooding."""
    activity = _simulate_voice_activity(_daily([1, 2], days=60, seconds=12 * HOUR))
    assert activity == 2 / BREADTH_SATURATION_VOICES
    assert root_spread(activity) == 0.0


def test_a_genuine_voice_community_earns_the_whole_root_system():
    """Six people in a call together an hour a day for a week — an unremarkable
    week for a server that actually lives in voice — saturates the reading. The
    bar is high, but it must not be unreachable, or the dimension would be
    decorative."""
    activity = _simulate_voice_activity(_daily(list(range(6)), days=7, seconds=HOUR))
    assert activity == 1.0
    assert root_spread(activity) == 1.0


def test_presence_still_costs_several_distinct_real_days():
    """One evening's call, however long, cannot buy presence for anybody in it:
    the per-person diminishing-returns window caps a single day's credits at
    well under the presence floor, exactly as it does for watering."""
    one_long_night = _simulate_voice_activity([(0.0, list(range(6)), 10 * HOUR)])
    assert one_long_night == 0.0

    over_days = _simulate_voice_activity(_daily(list(range(6)), days=4, seconds=HOUR))
    assert over_days > 0.0


def test_voice_presence_fades_when_a_server_stops_talking():
    """Voice activity reads recent reality, not a lifetime record: a server that
    lived in voice for a month and then went quiet falls back below the
    visibility threshold within weeks, and the root system recedes with it."""
    sessions = _daily(list(range(6)), days=30, seconds=2 * HOUR)
    assert _simulate_voice_activity(sessions) == 1.0

    later = _simulate_voice_activity(sessions, now=29 * DAY + 28 * DAY)
    assert root_spread(later) == 0.0


# --- Independence from breadth, rhythm and thread depth ------------------------
#
# The three growth modifiers had to be shown non-interfering by growing actual
# structures across every corner of each pair, because they genuinely share
# grow()'s branch and angle terms. Voice activity shares nothing with any of
# them: it is not a parameter of grow() at all. That makes the property provable
# rather than merely testable, and these tests state the proof's two halves.


def test_neither_function_has_anywhere_to_put_the_other_dimension():
    """The proof, stated as the two signatures it lives in: ``grow`` takes no
    voice argument, so no amount of voice activity can change a body; and
    ``root_spread`` takes nothing *but* voice activity, so no setting of breadth,
    rhythm or depth can change a root system. The three growth modifiers needed
    four-corner scenario tests to establish non-interference because they
    genuinely share grow()'s branch and angle terms; here there is no shared term
    to interfere through, and a signature change is what would break it."""
    grow_params = set(inspect.signature(grow).parameters)
    assert grow_params == {
        "structure", "genome", "moisture", "steps",
        "breadth", "rhythm", "reaction_warmth", "thread_depth",
    }
    assert set(inspect.signature(root_spread).parameters) == {"voice_activity"}


def test_the_root_system_behaves_the_same_on_every_kind_of_body():
    """The combined-scenario form the three growth modifiers ran against each
    other, applied here: grow four genuinely different bodies across the corners
    of breadth and thread depth, and confirm each one gains its root system at
    saturation and keeps it confined to its foot. Neither dimension's setting
    suppresses, amplifies or relocates the effect."""
    genome = genome_from_seed(TENDED_SEED)
    base = germinate(TENDED_SEED)
    corners = {
        (breadth, depth): grow(
            base, genome, TENDED, 400, breadth=breadth, rhythm=0.5, thread_depth=depth
        )
        for breadth in (0.0, 1.0)
        for depth in (0.5, 1.0)
    }
    sizes = {corner: len(body.nodes) for corner, body in corners.items()}
    assert len(set(sizes.values())) == len(sizes), f"corners must differ in body: {sizes}"

    for corner, body in corners.items():
        plain = Image.open(render.render(body, TENDED, genome)).convert("RGB")
        rooted = Image.open(render.render(body, TENDED, genome, 1.0)).convert("RGB")
        changed = [
            (x, y)
            for y in range(plain.height)
            for x in range(plain.width)
            if plain.getpixel((x, y)) != rooted.getpixel((x, y))
        ]
        share = len(changed) / (plain.width * plain.height)
        assert 0.005 < share < 0.05, f"{corner}: root system out of its measured band ({share})"
        assert min(y for _, y in changed) > 0.35 * plain.height, f"{corner}: reached the crown"


# --- "Subtle" as a measured bound, not an adjective ----------------------------
#
# The only tests here that draw. See the module docstring for why these two
# properties cannot be stated in pure logic.


def _changed_pixels(voice_activity: float) -> tuple[int, int, int]:
    """Render a mature plant with and without ``voice_activity`` and return
    ``(changed_pixel_count, total_pixels, topmost_changed_row)``."""
    genome = genome_from_seed(TENDED_SEED)
    body = grow(germinate(TENDED_SEED), genome, TENDED, 700, breadth=0.7, rhythm=0.5)
    plain = Image.open(render.render(body, TENDED, genome)).convert("RGB")
    rooted = Image.open(render.render(body, TENDED, genome, voice_activity)).convert("RGB")
    changed = [
        (x, y)
        for y in range(plain.height)
        for x in range(plain.width)
        if plain.getpixel((x, y)) != rooted.getpixel((x, y))
    ]
    total = plain.width * plain.height
    top = min((y for _, y in changed), default=plain.height)
    return len(changed), total, top


def test_below_the_threshold_the_image_is_byte_identical_not_merely_similar():
    """Every root visual is additive on top of a zero spread, so a server that
    never uses voice — and one where a duo calls daily — renders the exact bytes
    the pre-Phase-17 renderer produced. The same forced no-op _depth_exponent
    returns below its own neutral point, one layer further out."""
    import render

    genome = genome_from_seed(TENDED_SEED)
    body = grow(germinate(TENDED_SEED), genome, TENDED, 400)
    plain = render.render(body, TENDED, genome).getvalue()
    assert render.render(body, TENDED, genome, 0.0).getvalue() == plain
    assert render.render(body, TENDED, genome, VOICE_ROOT_THRESHOLD).getvalue() == plain
    assert render.render(body, TENDED, genome, 2 / BREADTH_SATURATION_VOICES).getvalue() == plain


def test_a_saturated_root_system_is_visible_but_stays_at_the_plants_foot():
    """"Subtle" as a number: at full saturation the root system moves a few
    percent of the frame — enough to find when looking at the picture, far short
    of the visual event a bloom or a drought is — and every pixel of it sits in
    the lower part of the image, at the foot of the trunk and in the soil."""
    changed, total, top = _changed_pixels(1.0)
    assert 0.005 < changed / total < 0.05
    assert top > 0.35 * 600  # render.HEIGHT: nothing in the crown moves


def test_the_first_visible_step_above_the_threshold_is_only_a_hint():
    """Four sustained voices — the first headcount that shows at all — must read
    as a suggestion of roots, not as roots: a fraction of the saturated effect,
    and a small fraction of the frame."""
    hinted, total, _ = _changed_pixels(4 / BREADTH_SATURATION_VOICES)
    saturated, _, _ = _changed_pixels(1.0)
    assert 0 < hinted < saturated / 3
    assert hinted / total < 0.01
