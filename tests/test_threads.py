"""Thread depth's qualification, anti-farming and independence properties (Phase 16).

Mirrors test_breadth.py and test_rhythm.py: exercises structure.thread_qualifies
and structure.thread_depth directly on hand-built per-thread aggregates — the
same shape bot.py's _guild_thread_depth builds by grouping the thread_activity
table's rows by thread — without touching storage or Discord at all. The final
section mirrors test_rhythm.py's own rigor against test_breadth.py: it grows
actual structures to confirm depth and crown breadth vary independently rather
than one washing out the other.
"""

from structure import (
    NEUTRAL_THREAD_DEPTH,
    THREAD_DEPTH_SATURATION_THREADS,
    THREAD_MIN_MESSAGES_PER_PARTICIPANT,
    THREAD_MIN_SPAN_SECONDS,
    genome_from_seed,
    germinate,
    grow,
    serialize,
    thread_depth,
    thread_qualifies,
)

DAY = 24.0 * 60 * 60
HOUR = 60.0 * 60
#: Vitality a lively channel holds — matches test_structure.py's TENDED.
TENDED = 0.75
#: A seed with genes spread across their ranges — matches test_structure.py's
#: TENDED_SEED, reused here for the same reason: a real, non-degenerate genome.
TENDED_SEED = 0x2F3A9C41D77E5B2


# --- Qualification: what counts as a genuine, sustained thread -----------------


def test_a_monologue_never_qualifies():
    """One person posting any number of times in their own thread never counts
    toward depth — there is no second voice to make it a conversation at all."""
    assert not thread_qualifies([50], 0.0, 30 * DAY)


def test_a_barely_touched_thread_never_qualifies():
    """A thread nobody but its creator ever wrote in, or where a second person
    dropped by exactly once, contributes nothing — an opened-and-abandoned
    thread, or the cheapest possible padding attack, both fail the same bar."""
    assert not thread_qualifies([1], 0.0, 0.0)
    assert not thread_qualifies([5, 1], 0.0, 30 * DAY)  # second voice: one drive-by reply


def test_a_burst_posted_within_an_instant_does_not_qualify():
    """Two genuinely engaged participants, but every message landed within
    seconds of each other — a script, not a real unfolding conversation."""
    assert not thread_qualifies([4, 4], 0.0, 5.0)


def test_a_genuine_sustained_conversation_qualifies():
    """Two people, each posting several times, spread over a real span."""
    assert thread_qualifies([3, 4], 0.0, THREAD_MIN_SPAN_SECONDS)
    assert thread_qualifies([3, 4], 0.0, 3 * HOUR)


def test_qualification_sits_exactly_at_the_span_boundary():
    counts = [THREAD_MIN_MESSAGES_PER_PARTICIPANT, THREAD_MIN_MESSAGES_PER_PARTICIPANT]
    assert not thread_qualifies(counts, 0.0, THREAD_MIN_SPAN_SECONDS - 1)
    assert thread_qualifies(counts, 0.0, THREAD_MIN_SPAN_SECONDS)


def test_a_crowd_of_one_off_repliers_still_needs_the_message_floor():
    """Five distinct people who each only dropped a single message does not
    qualify either — headcount alone is not enough, exactly like a single
    extra message from one silent account is not enough (see above): every
    counted participant must show real, repeated engagement in the thread."""
    assert not thread_qualifies([1, 1, 1, 1, 1], 0.0, 10 * DAY)


# --- Thread depth: aggregate score from currently-qualifying thread counts -----


def test_no_qualifying_threads_reads_neutral_not_an_extreme():
    """The ordinary case for the overwhelming majority of servers, which never
    use threads at all — never a structural penalty (see NEUTRAL_THREAD_DEPTH's
    docstring for why this differs from author breadth's zero-voices extreme)."""
    assert thread_depth(0) == NEUTRAL_THREAD_DEPTH


def test_depth_rises_from_neutral_and_saturates():
    scores = [thread_depth(n) for n in range(THREAD_DEPTH_SATURATION_THREADS + 2)]
    assert scores[0] == NEUTRAL_THREAD_DEPTH
    assert all(b > a for a, b in zip(scores, scores[1 : THREAD_DEPTH_SATURATION_THREADS + 1]))
    assert scores[THREAD_DEPTH_SATURATION_THREADS] == 1.0
    assert scores[-1] == 1.0  # more than enough threads: still capped at 1.0


# --- Anti-farming: a single person alone cannot move depth ---------------------


def _qualifying_count(threads: list[tuple[list[int], float, float]]) -> int:
    """How many of ``threads`` (each a ``(participant_message_counts, first, last)``
    triple) clear :func:`thread_qualifies` — the aggregation bot.py's
    ``_guild_thread_depth`` performs over the ``thread_activity`` table's rows,
    grouped by thread."""
    return sum(1 for counts, first, last in threads if thread_qualifies(counts, first, last))


def test_one_person_opening_many_solo_threads_does_not_move_depth():
    """Someone opening ten threads and posting extensively in each, entirely
    alone, never qualifies a single one of them — depth stays neutral, exactly
    as if they had opened none at all."""
    solo_threads = [([100], 0.0, 60 * DAY) for _ in range(10)]
    qualifying = _qualifying_count(solo_threads)
    assert qualifying == 0
    assert thread_depth(qualifying) == NEUTRAL_THREAD_DEPTH


def test_padding_a_second_voice_with_one_message_per_thread_still_fails():
    """The cheapest possible attack against the two-voice bar: a second,
    otherwise-silent account drops exactly one message into each of many
    threads. Still fails the per-participant message floor in every one."""
    padded_threads = [([50, 1], 0.0, 60 * DAY) for _ in range(10)]
    assert _qualifying_count(padded_threads) == 0


def test_genuinely_sustained_multi_voice_threads_do_register():
    """Three real, sustained, multi-participant threads register as exactly
    that many qualifying threads and saturate depth."""
    threads = [
        ([4, 5], 0.0, 2 * HOUR),
        ([3, 3, 2], DAY, DAY + 5 * HOUR),
        ([6, 2], 5 * DAY, 5 * DAY + HOUR),
    ]
    qualifying = _qualifying_count(threads)
    assert qualifying == 3
    assert thread_depth(qualifying) == 1.0  # saturates at THREAD_DEPTH_SATURATION_THREADS == 3


def test_a_small_but_genuinely_thread_heavy_server_is_fairly_rewarded():
    """The attack this test guards against runs the other way: a qualification
    bar accidentally sized for a much larger server. Two real threads, each
    with only THREAD_MIN_PARTICIPANTS distinct people (not a
    BREADTH_SATURATION_VOICES-sized crowd), already moves depth clearly above
    neutral — depth rewards a *pattern* of thread use, not a second reading of
    channel-wide breadth."""
    threads = [([3, 3], 0.0, HOUR), ([2, 4], DAY, DAY + 2 * HOUR)]
    qualifying = _qualifying_count(threads)
    assert qualifying == 2
    score = thread_depth(qualifying)
    assert NEUTRAL_THREAD_DEPTH < score < 1.0


# --- Depth and breadth vary independently on the growth model itself -----------
#
# The same rigor test_rhythm.py applied against test_breadth.py: grow actual
# structures under every combination of a low/high breadth and a low/high
# thread depth, and confirm each dimension's own signature shows up regardless
# of what the other dimension is doing — neither washes the other out.
#
# Two metrics, deliberately chosen to each track one dimension specifically:
# the fraction of nodes at branch order >= 5 (deep nesting — thread depth's own
# lever, see _depth_exponent, which has *zero* effect at order 0) versus the
# total accumulated node count (overall crown volume — breadth's flat per-order
# branch_multiplier pushes this up at every order alike, including order 0,
# where depth cannot reach at all).


def _grown(breadth: float, depth: float, steps: int = 500):
    genome = genome_from_seed(TENDED_SEED)
    return grow(
        germinate(TENDED_SEED), genome, TENDED, steps, breadth=breadth, rhythm=0.5, thread_depth=depth
    )


def _deep_fraction(body) -> float:
    """Fraction of accumulated nodes nested at branch order 5 or deeper."""
    return sum(1 for node in body.nodes if node.order >= 5) / len(body.nodes)


def test_high_depth_alone_grows_deeper_nesting_at_fixed_breadth():
    shallow = _grown(breadth=0.5, depth=0.0)
    deep = _grown(breadth=0.5, depth=1.0)
    assert _deep_fraction(deep) > _deep_fraction(shallow) * 3  # not a marginal shift


def test_depth_at_or_below_neutral_never_differs_from_the_pre_phase_16_default():
    """NEUTRAL_THREAD_DEPTH and below are all exactly the no-effect baseline —
    not merely a smaller effect, a byte-identical structure to a caller that
    never passes thread_depth at all (see grow()'s default)."""
    genome = genome_from_seed(TENDED_SEED)
    base = germinate(TENDED_SEED)

    unset = grow(base, genome, TENDED, 300, breadth=0.7, rhythm=0.3)
    explicit_neutral = grow(base, genome, TENDED, 300, breadth=0.7, rhythm=0.3, thread_depth=NEUTRAL_THREAD_DEPTH)
    below_neutral = grow(base, genome, TENDED, 300, breadth=0.7, rhythm=0.3, thread_depth=0.0)

    assert serialize(unset) == serialize(explicit_neutral) == serialize(below_neutral)


def test_depth_and_breadth_vary_independently_across_all_four_corners():
    """High/low breadth crossed with high/low thread depth: each dimension's
    own effect holds in the presence of every setting of the other, so neither
    washes the other out."""
    corners = {
        (breadth, depth): _grown(breadth, depth) for breadth in (0.0, 1.0) for depth in (0.0, 1.0)
    }

    # Depth's signature (deep-order fraction) holds at both breadth extremes.
    assert _deep_fraction(corners[(0.0, 1.0)]) > _deep_fraction(corners[(0.0, 0.0)])
    assert _deep_fraction(corners[(1.0, 1.0)]) > _deep_fraction(corners[(1.0, 0.0)])

    # Breadth's signature (overall accumulated size) holds at both depth extremes.
    assert len(corners[(1.0, 0.0)].nodes) > len(corners[(0.0, 0.0)].nodes)
    assert len(corners[(1.0, 1.0)].nodes) > len(corners[(0.0, 1.0)].nodes)

    # And a low-breadth, high-depth plant nests distinctly deeper than a
    # high-breadth, low-depth one of otherwise identical health — the two
    # dimensions genuinely trade off rather than one dominating the other.
    assert _deep_fraction(corners[(0.0, 1.0)]) > _deep_fraction(corners[(1.0, 0.0)])
