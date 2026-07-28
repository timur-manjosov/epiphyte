"""Pure body logic for Epiphyte: the plant's accumulating body and its scars.

No side effects, no clock reads, no ``import discord`` and no Pillow. Given the
same inputs these functions always return the same outputs, which makes them
testable with pytest without drawing anything or starting Discord.

This module replaces the old "moisture -> L-system depth -> fixed shape" model.
A plant is no longer a function of its current moisture: it is the accumulated
result of its whole life. Growth is applied in discrete steps, each step advances
every living tip a little, and what has grown stays part of the body.

Vitality and body are decoupled. When moisture is healthy the plant grows; when
it is parched the plant dies back from the outside in, turning living wood into
dead wood. Dead wood is never removed and never revives, so a drought is written
permanently into the body — a scar still legible long after the plant recovers.

A drought that never lifts reaches the base and kills the whole plant: once every
node is dead the plant is dead. From that death a successor germinates — a
single-gene mutation of the parent's seed, so it resembles the parent yet is its
own individual — carrying the lineage (generation and parent seed) forward. There
is no final state; the line simply continues.

Above growth and death sit the milestones, and they are thresholds rather than
stages. The plant banks a reserve of healthy time; once that bank is full and its
body is mature it comes into bloom, and flowering then spends the bank down until
the bloom ends by itself — so a season emerges from the rules instead of being
scheduled, and the next one has to be earned again. A long enough bloom sets seed,
which stays and enriches what the line hands on. And a tree grown very old, very
large and flowered many times over can take on an epiphyte: a tiny second organism
with its own mini-genome, riding one of its host's old limbs. None of it can be
forced by a burst of activity — only accumulated.

Two plants with the same ``seed`` are identical (same :class:`Genome`, same
growth) — that seeded determinism *is* each plant's individuality. Growth is
also chunk-invariant: running ``steps`` steps at once yields exactly the same
structure as running the same steps one at a time, because every decision is
seeded by ``(seed, node_id, step_index)`` and never by call boundaries.

Message volume is not the only signal that shapes the body: author breadth
(:func:`author_breadth`), how many distinct people the channel's recent activity
comes from, additionally scales how eagerly the crown forks versus merely
extends — a many-voiced channel grows a wider, bushier crown than an equally
healthy but single-voiced one, at the same overall size.

Temporal rhythm (:func:`temporal_rhythm`) is a second, independent signal: how
evenly the channel's daily activity is spread over time, as opposed to how many
people it comes from. A channel with a steady day-to-day cadence scales down the
organic angle noise applied to every internode, growing a calmer, more symmetric
body; a channel whose activity comes in occasional bursts scales that noise up,
growing a more irregular, gnarled one — at the same size and the same crown
breadth, since it touches a different knob than :func:`author_breadth` does.

Reactions are a third signal, but a differently-shaped one: instead of steering
growth every step like breadth and rhythm do, ``reaction_warmth`` (read the same
way :func:`author_breadth` reads presence weights, just over reactors rather than
message authors — see ``bot.py``) is sampled only at the instant a bloom already
earned by Phase 9's own maturity/health gate begins, and becomes that bloom's
:attr:`LifeStats.bloom_intensity` for its whole duration (:func:`_bloom_intensity`).
There is deliberately no running "reaction score" to watch tick by tick — only,
occasionally, a bloom whose vividness reflects how broadly (not how loudly) the
channel has been reacting over the same long window the health/maturity gate
already reads. It never affects *whether* a bloom happens, never touches growth,
branching or moisture, and a quiet-but-healthy channel still blooms, just modestly.

Threads are a fourth signal, and — like breadth and rhythm — steer growth every
step rather than sitting to one side like reaction warmth does. A Discord thread
is, structurally, a conversation branching off the trunk and developing its own
life for a while — close to a literal description of a side branch that itself
branches further — so :func:`thread_depth` (read from qualifying threads the
caller, ``bot.py``, currently counts as sustained via :func:`thread_qualifies`)
scales how far branch probability persists into higher orders instead of
quenching near the trunk (:func:`_depth_exponent`). This is deliberately a
*different* knob from both of ``grow()``'s other structural modifiers: breadth's
``branch_multiplier`` scales branch chance flatly at every order alike (crown
*width*), rhythm's ``jitter_multiplier`` scales angle noise, and thread depth's
``depth_exponent`` scales only how the per-order decay curve falls off (crown
*depth* — how many generations of nesting a fork tends to keep producing). A
channel whose conversations regularly spin off into sustained, multi-voice
threads grows a more deeply nested branch structure than an equally healthy,
equally wide-crowned one whose activity stays flat in the main channel. Unlike
author breadth, a channel that has simply never used threads at all — the
ordinary case for most servers — is never penalised for it: see
:data:`NEUTRAL_THREAD_DEPTH`.

Voice-channel activity is a fifth signal, and the quietest one in the whole
model. Text, reactions and threads are all visible in the room; time spent
talking in a voice channel is a parallel dimension of a community's life that
nobody scrolling the channel ever sees — the same way roots are the part of a
real plant nobody sees until they look for them. So it drives a root system and
a thickened trunk base (``root_spread``, read by ``render.py``) rather than any
part of the branching model, and it does so *only* past a deliberately high
threshold: see :func:`root_spread`. What counts as genuine voice activity is
:func:`voice_is_audible` and :func:`shared_voice_seconds` — a person alone in a
channel, or sitting muted, deafened or parked in the guild's AFK channel, earns
nothing at all, however long they stay.

Note that this signal touches *nothing* :func:`grow` computes: it is never
passed to :func:`grow`, so a body grown under any amount of voice activity is
byte-identical to one grown under none. Its independence from author breadth,
temporal rhythm and thread depth is therefore structural rather than merely
tested — there is no shared term for the four to interact through.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import Enum

# --- Growth constants (rules, not user configuration) ------------------------
#
# The dynamics are deliberately self-limiting. Below its carrying capacity a
# plant only grows — tips extend and branch, and nothing is ever removed, so it
# can never go extinct and freeze. Above capacity, extending tips cap off under a
# termination pressure that keeps the crown near capacity while it keeps turning
# over — old tips finish, new ones branch out — so branches stay finite and the
# crown stays bushy rather than growing into a bundle of endless parallel whips.
# Moisture sets the *pace* of growth; the genome's vigour sets how big the crown
# gets. Growth can neither explode nor die out; it accumulates, faster when wet.

#: Fraction of full moisture that becomes a tip's per-step chance to extend. Even
#: a soaked plant grows at a measured pace, so a big tree takes weeks of health.
EXTENSION_RATE: float = 0.5
#: Baseline crown carrying capacity (active tips) at vigour ``1.0``; scaled by the
#: genome's vigour so some plants stay sparse and others grow dense.
BASE_CAPACITY: float = 12.0
#: Floor on carrying capacity, so even a low-vigour plant can branch a little.
MIN_CAPACITY: int = 4
#: How hard the crown is trimmed once over capacity: an extending tip's chance to
#: cap off is this times the fractional overshoot (bounded by MAX_TERMINATION).
OVERCAPACITY_PRESSURE: float = 1.5
#: Ceiling on that per-tip termination chance, so an overshoot is trimmed back
#: gradually over several steps rather than the whole crown capping off at once.
MAX_TERMINATION: float = 0.6
#: Branch generations beyond which tips only extend, never fork. Bounds depth.
MAX_ORDER: int = 6
#: Per-order decay of the branching chance (apical dominance): higher-order side
#: branches split far less often than the main axis, giving the natural "few big
#: branches, many fine twigs" look.
BRANCH_ORDER_DECAY: float = 0.5
#: Per-order shortening of internodes: twigs are shorter than the trunk.
LENGTH_ORDER_DECAY: float = 0.9
#: Fractional random spread applied to each internode's length (organic noise).
LENGTH_JITTER: float = 0.15
#: The direction the main axis is gently pulled toward, in degrees (straight up).
UPRIGHT_ANGLE: float = 90.0
#: How far from upright a new limb may set out. Branches spread; they never dive.
MAX_BRANCH_SPREAD: float = 62.0

# --- Breadth constants (how many voices, not just how much) ------------------
#
# The first vitality dimension beyond message-count-driven growth: how many
# distinct people are talking, not how much total volume there is. An author's
# presence weight lives and decays on the same [0, 1] scale as moisture (see
# ``moisture.decay``/``moisture.water``), but the caller (``bot.py``) tops it up
# with the *same already-anti-farmed amount* moisture.next_watering computes for
# that message — so, exactly like moisture itself, a single account cannot buy
# presence by flooding; it still costs real elapsed days. Breadth only ever
# scales branch_probability — how often a tip forks rather than merely extends
# — never capacity, moisture, size or colour, so it stays a legible, narrow
# effect: a many-voiced and a one-voiced channel of the same overall health
# end up the same size, just differently shaped.

#: Half-life (seconds) of a single author's presence weight. A week: an order of
#: magnitude above moisture's own one-day half-life, long enough to smooth
#: weekday/weekend noise in who is around, short enough that a channel which has
#: genuinely narrowed to one or two people sees breadth fall within weeks rather
#: than carrying a lifetime average forward — the same "recent reality, not
#: history" principle moisture already follows, just on the slower cadence a
#: structural trait needs to be legible on.
AUTHOR_PRESENCE_HALF_LIFE_SECONDS: float = 7 * 24 * 60 * 60  # 1 week
#: Presence weight an author must accumulate before counting as one of the
#: plant's active recent voices. Because that weight only rises by the same
#: anti-farmed amount moisture does, a fresh account needs several distinct real
#: days of showing up to cross this — a single drive-by message, or a burst of
#: messages within one day, does not register.
AUTHOR_PRESENCE_FLOOR: float = 0.3
#: Distinct active voices at which author breadth saturates (1.0). Six — the
#: same order of magnitude as the modest crowd that clears HEALTHY in
#: test_farming.py's anti-farming demonstration, so it takes a real
#: conversation, not a couple of accounts, to fill out a wide crown.
BREADTH_SATURATION_VOICES: int = 6
#: Range author breadth scales a tip's branch chance across. Neutral (1.0) sits
#: at breadth 0.5, which is what grow() defaults to when a caller does not pass
#: breadth at all — so every pre-Phase-11 call site is unaffected.
BREADTH_BRANCH_MULTIPLIER_MIN: float = 0.7
BREADTH_BRANCH_MULTIPLIER_MAX: float = 1.3

# --- Rhythm constants (how evenly, not just how much or by whom) -------------
#
# The second vitality dimension beyond message-count-driven growth: how evenly a
# channel's activity is spread across days, independent of total volume and of
# author breadth. It touches a different lever than breadth (organic angle noise,
# not branch chance), so the two stay legible and non-interfering side by side —
# see grow()'s docstring. Rhythm is read from ``daily_activity``, one row per
# guild per calendar day, already being written for exactly this purpose; no new
# Discord event is captured, only a new analysis over totals bot.py already knows.

#: Length, in whole calendar days, of the rolling window temporal_rhythm() reads.
#: Four times AUTHOR_PRESENCE_HALF_LIFE_SECONDS's week: rhythm is meant to read a
#: community's slower-moving character, not this week's mood, so one anomalous
#: week is diluted to a small fraction of the window instead of dominating it.
RHYTHM_WINDOW_DAYS: int = 56  # 8 weeks
#: Calendar days a window must have seen at least one message on before
#: temporal_rhythm() trusts the computed score at all. Below this a server is
#: either too young to have filled the window, or too quiet to have a real daily
#: pattern yet — both read as "not enough signal", not as a genuinely bursty one.
RHYTHM_MIN_ACTIVE_DAYS: int = 10
#: Rhythm score returned when there is not yet enough signal to trust — the same
#: "no effect, no judgement" role BREADTH_BRANCH_MULTIPLIER_MIN/MAX's midpoint
#: plays for breadth, and what grow() defaults to when a caller does not pass
#: rhythm at all.
NEUTRAL_RHYTHM: float = 0.5
#: Range temporal rhythm scales a new internode's organic angle-noise amplitude
#: across. A perfectly steady channel (rhythm 1.0) calms the noise down to
#: RHYTHM_JITTER_MULTIPLIER_MIN; a heavily bursty one (rhythm 0.0) amplifies it up
#: to RHYTHM_JITTER_MULTIPLIER_MAX. Neutral (1.0, no effect) sits at rhythm 0.5 —
#: NEUTRAL_RHYTHM — so a pre-Phase-12 call site is unaffected.
RHYTHM_JITTER_MULTIPLIER_MIN: float = 0.6
RHYTHM_JITTER_MULTIPLIER_MAX: float = 1.4

# --- Thread-depth constants (how deeply, not just how often or how evenly) ---
#
# The fourth vitality dimension beyond message-count-driven growth: how much of
# a channel's activity spins off into sustained, multi-voice threads, as opposed
# to who is talking (breadth) or how evenly (rhythm). A thread is a conversation
# branching off the trunk and developing its own life for a while — close to a
# literal description of a side branch that itself branches further — so this
# scales how far branch probability persists into higher orders rather than
# breadth's flat per-order chance or rhythm's angle noise. Qualification
# (:func:`thread_qualifies`) is deliberately its own, simpler shape of data than
# author/reactor presence's decayed weights: a thread's whole short life is a
# handful of rows, not a value that needs to fade continuously over weeks.

#: A thread must be posted in by at least this many distinct people, each past
#: :data:`THREAD_MIN_MESSAGES_PER_PARTICIPANT`, before it counts as a genuine
#: side conversation rather than one person's monologue — the same headcount
#: floor breadth and reaction warmth use against a lone actor, applied at the
#: scale of a single thread instead of a whole channel. Deliberately far below
#: :data:`BREADTH_SATURATION_VOICES`: depth rewards a *pattern* of thread use,
#: not a second reading of channel-wide breadth, so a small server with only a
#: handful of members can still earn it through genuine, real conversations.
THREAD_MIN_PARTICIPANTS: int = 2
#: Messages a participant must have posted in the thread to count toward
#: :data:`THREAD_MIN_PARTICIPANTS`. Without this, a single extra message from
#: an otherwise-silent second account would be enough to qualify a thread that
#: is really still one person's monologue — the direct defence the admission
#: test's naive-reaction-count example calls for, applied here.
THREAD_MIN_MESSAGES_PER_PARTICIPANT: int = 2
#: How long, in real seconds, a thread's first and most recent qualifying
#: message must be apart before it counts. Filters out a burst posted within
#: the same instant (a script, or a moment of copy-pasting from several
#: accounts at once) while staying short enough that an ordinary, fast-moving
#: real conversation — most genuine threads resolve within hours, not days —
#: still clears it easily; calibrating this to breadth's week-long scale would
#: wrongly demand a multi-day thread just to prove it is real.
THREAD_MIN_SPAN_SECONDS: float = 30 * 60  # 30 minutes
#: How long a qualifying thread's contribution is still counted after its last
#: message, mirroring how a presence weight fades rather than cutting off the
#: instant activity stops. The same order of magnitude as
#: :data:`AUTHOR_PRESENCE_HALF_LIFE_SECONDS`, so a thread that wrapped up a few
#: days ago still reads as recently alive, but one abandoned long ago does not.
THREAD_RECENCY_SECONDS: float = 7 * 24 * 60 * 60  # 1 week
#: Currently-live qualifying threads at which thread depth saturates (1.0).
#: Three — far below :data:`BREADTH_SATURATION_VOICES`'s six, for the same
#: reason :data:`THREAD_MIN_PARTICIPANTS` is: a genuinely thread-heavy small
#: server should not be held to a bar sized for a much larger one.
THREAD_DEPTH_SATURATION_THREADS: int = 3
#: Depth score when there are no currently-qualifying threads at all — the
#: default for the overwhelming majority of servers, which simply never use
#: threads, an opt-in Discord feature many communities never touch. Unlike
#: author breadth, where zero voices is a genuine, reliable extreme (a plant
#: with any moisture always has at least one author), zero threads is the
#: ordinary case and must never read as a permanent structural penalty — it is
#: treated the way :func:`temporal_rhythm` treats too little history: an
#: abstention, not a verdict. Thread depth therefore only ever moves *up* from
#: here as real, sustained thread use accumulates; there is no symmetric
#: "worse than never threading" reading, since nothing distinguishes that from
#: simply not having used the feature yet. Also what ``grow()`` defaults to
#: when a caller does not pass ``thread_depth`` at all, so a pre-Phase-16 call
#: site is unaffected.
NEUTRAL_THREAD_DEPTH: float = 0.5
#: Floor the branch-order decay's exponent scales down to (see
#: :func:`_depth_exponent`) as thread depth rises from
#: :data:`NEUTRAL_THREAD_DEPTH` to ``1.0``. Below neutral the exponent is
#: always exactly ``1.0`` — :data:`BRANCH_ORDER_DECAY` behaves precisely as it
#: always did pre-Phase-16 — so this only ever lets deep branch structures
#: persist to higher orders than the baseline, never quenches them faster.
DEPTH_ORDER_EXPONENT_MIN: float = 0.55

# --- Voice constants (the room nobody scrolling ever sees) -------------------
#
# The fifth vitality dimension, and deliberately the most understated one in the
# model. It is also the only one that touches no part of grow() at all: it drives
# the root system and the trunk's basal flare in render.py, which is genuinely new
# visual territory rather than another reading of the crown. That placement is
# what makes it provably independent of author breadth, temporal rhythm and thread
# depth — those three share grow()'s branch/angle terms and had to be shown not to
# interfere; voice activity has no term in common with any of them to interfere
# through.
#
# The distinct-presence reading itself is deliberately *not* recalibrated here:
# bot.py feeds voice presence weights straight into author_breadth(), exactly as
# it already does for reaction warmth. "How many distinct people cleared the
# presence floor, saturating at a modest count" is the same anti-clique property
# this signal needs, and BREADTH_SATURATION_VOICES's bar is, if anything, harder
# to clear in a voice channel than in a text one — being audible together
# requires simultaneity, which posting does not — which is exactly right for a
# dimension that is meant to stay hidden until it is genuinely earned. All the
# voice-specific calibration lives in root_spread() instead.

#: Distinct audible people who must be in the *same* voice channel at the same
#: moment before any of that time counts (see :func:`shared_voice_seconds`).
#: One person sitting alone in a channel, muted or not, for however many hours,
#: earns exactly nothing — the direct answer to the admission test's
#: "not farmable by a single person alone", and a stricter one than the text
#: signals can manage, since here the requirement is simultaneity rather than a
#: per-person cap on an amount.
VOICE_MIN_AUDIBLE: int = 2
#: Shared audible time that earns one participant one watering-shaped credit
#: toward their voice presence weight. Fifteen minutes: long enough that a
#: dip-in-and-out cannot mint credits, short enough that an ordinary call
#: earns several. The credits themselves then run through the same per-person
#: diminishing-returns window as watering (``moisture.next_watering``, see
#: ``bot.py``), so a whole day spent in voice is worth a small, capped amount
#: and real presence still costs several distinct real days.
VOICE_CREDIT_SECONDS: float = 15 * 60
#: Voice activity below which the root system is *completely* invisible — not a
#: small effect, exactly none (:func:`root_spread` returns ``0.0``, and every
#: root visual in ``render.py`` is purely additive on top of that zero). At
#: :data:`BREADTH_SATURATION_VOICES` of six, this is three distinct people each
#: holding sustained voice presence: a duo who call each other daily is not what
#: "this server has a hidden life in voice" means, and must not read as it.
VOICE_ROOT_THRESHOLD: float = 0.5
#: Curvature of the emergence past that threshold. Two: the root system does not
#: fade in linearly from the threshold but starts almost imperceptibly and only
#: becomes clearly legible near saturation, so the visible band is the top of the
#: range rather than the whole of it — "subtle" as a shape, not as an adjective.
VOICE_ROOT_EXPONENT: float = 2.0

# --- Dieback constants (the body remembers drought) --------------------------
#
# Vitality (moisture) and body are decoupled. Above the threshold the plant lives
# and grows; below it the plant is parched and dies back from the outside in.
# Dead wood is never removed and never revives, so a drought leaves a permanent
# scar in the body that stays legible long after the plant has recovered.

#: Vitality below which the plant stops growing and begins to die back. Set deep
#: inside the withered band, so only a real, sustained drought kills wood.
DIEBACK_MOISTURE_THRESHOLD: float = 0.08
#: Chance an exposed living end dies in one step at zero vitality.
DIEBACK_MAX_RATE: float = 0.5
#: Steepness of the dieback curve in the drought's severity. High, so a moderate
#: drought only nibbles the outer crown (Phase 7's partial scars, with survivors),
#: while a lasting silence that drives vitality to zero collapses the whole plant
#: at pace — the difference between a bad week and abandonment.
DIEBACK_EXPONENT: float = 2.5

# --- Milestone constants (the rare states, earned over a whole life) ----------
#
# These are thresholds on what the plant has actually accumulated, never stages it
# passes through on a timer. Flowering needs a long bank of healthy time *and* a
# mature body, so no single busy evening can buy it; the bloom then spends that
# bank down and ends by itself, and the next one has to be earned again — a season
# emerging from the rules rather than scheduled. Seed is set by a bloom that lasts,
# and an epiphyte settles only on a tree so old, so large and so often flowered
# that short-term activity cannot reach it.

#: Vitality at or above which a step counts as healthy: the plant banks reserve and
#: is able to flower. Set inside the healthy band, so it takes a handful of people
#: watering a channel day after day — one person's capped share cannot hold it.
BLOOM_VITALITY: float = 0.55
#: Vitality below which an open bloom wilts. Far under the threshold that opened it,
#: because a channel breathes — busy by day, quiet overnight, quieter at the weekend
#: — and a flowering that closed every night would be a readout of the hour rather
#: than of a season. At the decay rate this is about a day of real silence.
BLOOM_WILT_VITALITY: float = 0.25
#: Banked healthy steps a plant must hold before it comes into bloom. At one tick
#: an hour that is a fortnight of sustained health.
BLOOM_HEALTHY_STEPS: int = 336
#: Reserve spent per step while flowering. Above the one banked per healthy step,
#: so a bloom drains its own bank and ends — even under unbroken care.
BLOOM_COST: int = 2
#: Body a plant needs before it can flower at all. A barely-healthy channel banks
#: reserve just as fast as a thriving one but grows far slower, so this is what
#: makes a lush channel flower sooner than a merely adequate one.
BLOOM_MIN_NODES: int = 1200
#: Steps in bloom after which the plant sets seed — a lasting flowering, not a
#: brief one. Seed, once set, stays on the body.
SEED_BLOOM_STEPS: int = 168

#: Vividness a bloom opens with when reaction_warmth is zero — a healthy but
#: socially quiet channel is never denied the bloom it earned, only shown a
#: modest one. Set well above zero so "no reactions at all" still reads as a
#: bloom, not as a blank one (see :func:`_bloom_intensity`).
BLOOM_INTENSITY_FLOOR: float = 0.2
#: Bloom intensity at or above which the plant speaks of an unusually vivid
#: bloom rather than an ordinary, earned one (see ``voice.py``). Set past the
#: floor's midpoint to the saturated range, so "vivid" genuinely means broad,
#: sustained warmth rather than merely non-zero reactions.
VIVID_BLOOM_THRESHOLD: float = 0.6

#: Age, body and number of flowerings a tree needs before an epiphyte takes hold.
#: Three months of life, a large body and several seasons of bloom behind it.
EPIPHYTE_MIN_AGE: int = 2160
EPIPHYTE_MIN_NODES: int = 2800
EPIPHYTE_MIN_BLOOMS: int = 3
#: How far into the host's past the limb it settles on must reach: an epiphyte
#: takes hold on old wood, never on this week's twigs.
EPIPHYTE_HOST_MATURITY: float = 0.5
#: How far up the host that limb must sit. An epiphyte rides in the crown, not on
#: the ankle of the trunk where it would just look like undergrowth.
EPIPHYTE_HOST_MIN_HEIGHT: float = 0.35
#: How far the epiphyte's inherited vigour, and the size of its parts, are dwarfed.
#: It is a tiny second organism on a branch, never a second tree.
EPIPHYTE_VIGOR_SCALE: float = 0.25
EPIPHYTE_SIZE_SCALE: float = 0.6
#: How much slower than its host the epiphyte grows. Host and epiphyte both
#: accumulate for as long as they live, so it is this ratio — not any cap — that
#: keeps the passenger small next to the tree however old the pair get.
EPIPHYTE_PACE: float = 0.4


class NodeState(Enum):
    """A node's vitality: growing tip, living wood, or dead wood (a scar)."""

    TIP = "tip"
    WOODY = "woody"
    DEAD = "dead"


@dataclass(frozen=True)
class Node:
    """A single point in the plant's body, in the plant's own coordinate space.

    ``+y`` points up. ``angle`` is the growth heading in degrees (measured
    counter-clockwise from ``+x``, so ``90`` is straight up), and ``axis_angle`` is
    the bearing of the limb this node belongs to — the heading its tropism pulls it
    back toward, upright on the main axis and outward on a branch. ``order`` is the
    branching generation (``0`` on the main axis). ``birth_step`` records the
    growth step the node was created in. Node ids are assigned sequentially, so a
    node's id equals its index in :attr:`Structure.nodes` and every child's
    ``parent_id`` is strictly less than its own id. Thickness is *not* stored per
    node — the renderer derives it from how many tips a node carries (pipe model).
    """

    id: int
    parent_id: int | None
    x: float
    y: float
    angle: float
    birth_step: int
    order: int
    state: NodeState
    axis_angle: float = UPRIGHT_ANGLE


@dataclass(frozen=True)
class LifeStats:
    """What a plant has accumulated over its life — the ground of its milestones.

    ``healthy_steps`` is a *reserve*, not a tally: it rises by one for every step
    spent in health and is spent again by flowering, so it measures the care the
    plant has stored up and not yet used. ``bloom_steps`` and ``bloom_count`` only
    ever rise — how long the plant has flowered in total, and how many separate
    times it has come into bloom. ``in_bloom`` is its bloom state as of the last
    step, which is what lets a new flowering be told from a continuing one.
    ``bloom_intensity`` is sampled once, when a bloom begins, from the reaction
    warmth accumulated at that moment (:func:`_bloom_intensity`), and then held
    fixed for that bloom's whole duration — never a live, watchable value.
    """

    healthy_steps: int = 0
    bloom_steps: int = 0
    bloom_count: int = 0
    in_bloom: bool = False
    bloom_intensity: float = 0.0


@dataclass(frozen=True)
class Structure:
    """A plant body: its nodes as a tree, its ``seed``, age, lineage and milestones.

    ``nodes`` is ordered by id (``nodes[i].id == i``); ``nodes[0]`` is the germ.
    ``step_count`` is how many growth steps have been applied so far, and doubles
    as the index of the next step to run. ``generation`` is ``1`` for a founding
    plant and rises with each successor; ``parent_seed`` is the seed of the
    predecessor this plant sprang from (``None`` for a founder) and
    ``lineage_blooms`` counts the ancestors that lived long enough to set seed, so
    the body carries its own lineage. ``stats`` accumulates this plant's own life,
    and ``epiphyte`` is the second organism it may come to carry.
    """

    nodes: tuple[Node, ...]
    step_count: int
    seed: int
    generation: int = 1
    parent_seed: int | None = None
    lineage_blooms: int = 0
    stats: LifeStats = LifeStats()
    epiphyte: Epiphyte | None = None
    #: Ids of the nodes currently in :attr:`NodeState.TIP`, in ascending order.
    #: A cache of what a full scan of ``nodes`` for that state would find — kept
    #: incrementally by :func:`_growth_step` so a step's cost tracks the crown's
    #: active tip count (bounded by capacity) rather than the accumulated body
    #: size. Not part of :func:`serialize`'s output since it is fully derived from
    #: ``nodes``; :func:`deserialize` recomputes it once on load.
    active_tips: tuple[int, ...] = ()


@dataclass(frozen=True)
class Epiphyte:
    """A tiny second organism riding on one of its host's old limbs.

    Taking the project's name literally: a plant that grew old, large and flowered
    enough times can come to carry one. It is a plant in its own right — the same
    :class:`Structure`, grown by the same rules — with its own seed and a dwarfed
    mini-genome derived from the host's, anchored at ``host_node_id`` and living in
    coordinates relative to that limb. It shares its host's weather, so it grows
    and dies back with it.
    """

    host_node_id: int
    structure: Structure


@dataclass(frozen=True)
class Genome:
    """The heritable shape parameters of a plant, derived from its seed.

    Same seed ⇒ same genome ⇒ same plant. The genes shape *how* the body grows,
    while the per-node seeded randomness decides *what* each individual tip does.
    """

    #: Mean angle (degrees) a side branch diverges from its parent's heading.
    branch_angle: float
    #: Spread (degrees) of the organic angle noise on every new internode.
    angle_jitter: float
    #: Base chance an active tip branches (before per-order decay).
    branch_probability: float
    #: Base internode length in plant-space units.
    internode_length: float
    #: Strength (0..1) of the pull back toward vertical on each new internode.
    gravitropism: float
    #: Growth vigour: scales how readily tips act at a given moisture.
    vigor: float
    #: Leaf size multiplier — how large this plant's individual leaves render.
    leaf_size: float
    #: Leaf density multiplier — how thickly living tips are foliaged.
    leaf_density: float
    #: Blossom hue as a position (0..1) along the renderer's accent range, so a
    #: plant that reaches bloom flowers in a colour that is its own.
    bloom_hue: float


# --- Heredity: genes packed into the seed's bit-fields -------------------------
#
# Each gene is an independent bit-field of the seed, scaled into its range below.
# Because the genes are independent, a mutation can re-roll a single trait while
# the child inherits all the others — so a descendant clearly resembles its parent
# yet is its own individual, and a lineage drifts one trait at a time.
_GENE_BITS = 7
_GENE_MAX = (1 << _GENE_BITS) - 1  # 127 levels per gene
_GENE_COUNT = 9                    # nine genes -> 63 of the seed's bits


def _allele(seed: int, index: int) -> float:
    """Read gene ``index`` from the seed's bit-field as a value in ``[0, 1]``."""
    return ((seed >> (index * _GENE_BITS)) & _GENE_MAX) / _GENE_MAX


def _scaled(low: float, high: float, allele: float) -> float:
    """Scale a ``[0, 1]`` allele into the gene's ``[low, high]`` range."""
    return low + allele * (high - low)


def genome_from_seed(seed: int) -> Genome:
    """Derive a plant's :class:`Genome` deterministically from an integer seed.

    Each gene reads an independent bit-field of the seed, so two seeds differing in
    one field share every other trait — which is what lets :func:`mutate` breed a
    recognisable but distinct descendant.
    """
    return Genome(
        branch_angle=_scaled(26.0, 50.0, _allele(seed, 0)),
        angle_jitter=_scaled(4.0, 9.0, _allele(seed, 1)),
        branch_probability=_scaled(0.18, 0.34, _allele(seed, 2)),
        internode_length=_scaled(8.0, 13.0, _allele(seed, 3)),
        gravitropism=_scaled(0.04, 0.12, _allele(seed, 4)),
        vigor=_scaled(0.8, 1.3, _allele(seed, 5)),
        leaf_size=_scaled(0.8, 1.4, _allele(seed, 6)),
        leaf_density=_scaled(0.7, 1.5, _allele(seed, 7)),
        bloom_hue=_allele(seed, 8),
    )


def mutate(seed: int) -> int:
    """Return a deterministic single-gene mutation of ``seed``.

    Exactly one gene's bit-field is re-rolled to a different value while every
    other gene is inherited unchanged, so the result is always different from
    ``seed`` yet a close relative of it. Pure and deterministic.
    """
    rng = random.Random(f"epiphyte-mutate:{seed}")
    shift = rng.randrange(_GENE_COUNT) * _GENE_BITS
    allele = (seed >> shift) & _GENE_MAX
    changed = allele ^ rng.randint(1, _GENE_MAX)  # nonzero xor -> guaranteed change
    return (seed & ~(_GENE_MAX << shift)) | (changed << shift)


def germinate(
    seed: int,
    generation: int = 1,
    parent_seed: int | None = None,
    lineage_blooms: int = 0,
) -> Structure:
    """Return a fresh structure: a single germ tip at the origin, growing up.

    ``generation``, ``parent_seed`` and ``lineage_blooms`` carry the lineage; a
    founding plant leaves them at their defaults (generation 1, no parent, an
    unflowered line). The milestones always start from nothing: an heir inherits
    its ancestors' record, never their accumulated life.
    """
    germ = Node(
        id=0,
        parent_id=None,
        x=0.0,
        y=0.0,
        angle=UPRIGHT_ANGLE,
        birth_step=0,
        order=0,
        state=NodeState.TIP,
    )
    return Structure(
        nodes=(germ,),
        step_count=0,
        seed=seed,
        generation=generation,
        parent_seed=parent_seed,
        lineage_blooms=lineage_blooms,
        active_tips=(0,),
    )


def is_dead(structure: Structure) -> bool:
    """True if every node is dead — the whole plant, inner wood and all, has died."""
    return all(node.state is NodeState.DEAD for node in structure.nodes)


def germinate_successor(structure: Structure) -> Structure:
    """Germinate a dead plant's successor: a mutated seed, the next generation.

    The successor's seed is a single-gene :func:`mutate` of the parent's, so it
    resembles the parent but is its own individual; ``generation`` rises by one and
    the parent's seed is recorded as lineage. A predecessor that lived long enough
    to set seed hands on a richer line — its flowering is counted into
    ``lineage_blooms`` — while one that died unflowered hands on only its shape.
    Pure — the caller (the adapter) decides *when* a dead plant reseeds.
    """
    return germinate(
        mutate(structure.seed),
        generation=structure.generation + 1,
        parent_seed=structure.seed,
        lineage_blooms=structure.lineage_blooms + (1 if has_seeded(structure) else 0),
    )


# --- Milestones: bloom, seed and the epiphyte ---------------------------------


def _bloom_state(size: int, healthy_steps: int, in_bloom: bool, vitality: float) -> bool:
    """Whether a plant of this size, reserve and bloom state flowers at ``vitality``.

    Coming *into* bloom takes a mature body, health, and a full bank of healthy time;
    staying in bloom takes only enough reserve left to pay for another step of it and
    a vitality that has not fallen away altogether. Both thresholds are therefore
    hysteretic: hard to reach, then held through the ordinary ebb and flow, and lost
    for good either when the bank runs dry or when the plant is truly left to dry out.
    """
    if size < BLOOM_MIN_NODES:
        return False
    if in_bloom:
        return vitality >= BLOOM_WILT_VITALITY and healthy_steps >= BLOOM_COST
    return vitality >= BLOOM_VITALITY and healthy_steps >= BLOOM_HEALTHY_STEPS


def is_blooming(structure: Structure, moisture: float) -> bool:
    """True if the plant is in bloom right now (pure, from its life statistics)."""
    return _bloom_state(
        len(structure.nodes), structure.stats.healthy_steps, structure.stats.in_bloom, moisture
    )


def has_seeded(structure: Structure) -> bool:
    """True once the plant has flowered long enough to set seed — and stays true.

    Seed is part of the accumulated body, like wood: a drought takes the blossoms
    but the seed heads it earned remain.
    """
    return structure.stats.bloom_steps >= SEED_BLOOM_STEPS


def _epiphyte_conditions_met(age: int, size: int, blooms: int) -> bool:
    """Whether age, body and flowerings together allow an epiphyte to take hold."""
    return (
        age >= EPIPHYTE_MIN_AGE
        and size >= EPIPHYTE_MIN_NODES
        and blooms >= EPIPHYTE_MIN_BLOOMS
    )


def can_host_epiphyte(structure: Structure) -> bool:
    """True if the plant is old, large and often-flowered enough to carry an epiphyte.

    A pure function of the life statistics: no single condition is enough, and none
    of the three can be reached by a burst of activity.
    """
    return _epiphyte_conditions_met(
        structure.step_count, len(structure.nodes), structure.stats.bloom_count
    )


def _epiphyte_seed(host_seed: int) -> int:
    """Derive the epiphyte's own seed from its host's (deterministic)."""
    return random.Random(f"epiphyte-seed:{host_seed}").getrandbits(_GENE_BITS * _GENE_COUNT)


def epiphyte_genome(host_seed: int) -> Genome:
    """The mini-genome of the epiphyte a host carries: its own genes, dwarfed.

    The seed is derived from the host's, so a given tree always grows the same
    little companion, but the genes are its own — and its vigour and the size of its
    parts are scaled far down, which is what keeps it a tuft on a branch rather than
    a second tree.
    """
    base = genome_from_seed(_epiphyte_seed(host_seed))
    return replace(
        base,
        vigor=base.vigor * EPIPHYTE_VIGOR_SCALE,
        internode_length=base.internode_length * EPIPHYTE_SIZE_SCALE,
        leaf_size=base.leaf_size * EPIPHYTE_SIZE_SCALE,
    )


def _clamp01(value: float) -> float:
    """Clamp ``value`` into ``[0.0, 1.0]``."""
    return max(0.0, min(1.0, value))


def _nudged_angle(
    base_angle: float,
    axis_angle: float,
    genome: Genome,
    rng: random.Random,
    jitter_multiplier: float = 1.0,
) -> float:
    """Pull ``base_angle`` back toward its limb's bearing by the genome's
    gravitropism, then add one organic jitter draw. Consumes one random number.

    Pulling toward the limb's own bearing rather than toward vertical is what lets
    a branch keep the direction it set out in: the trunk holds itself upright, a
    limb holds itself outward, and the tree keeps its proportions as it ages
    instead of drawing itself together into a vertical rope. ``jitter_multiplier``
    (see :func:`_jitter_multiplier`) scales the jitter draw's amplitude — temporal
    rhythm's only effect on growth, independent of author breadth's effect on
    branch chance.
    """
    toward_axis = base_angle + genome.gravitropism * (axis_angle - base_angle)
    jitter = genome.angle_jitter * jitter_multiplier
    return toward_axis + rng.uniform(-jitter, jitter)


def _limb_bearing(axis_angle: float, side: float, genome: Genome) -> float:
    """The bearing a new limb sets out on, and from then on holds.

    It diverges from the axis it grew from by the genome's branch angle, but never
    further from upright than :data:`MAX_BRANCH_SPREAD` — deep in a crown the
    divergences would otherwise pile up until a branch grew back down into the earth.
    """
    bearing = axis_angle + side * genome.branch_angle
    return max(UPRIGHT_ANGLE - MAX_BRANCH_SPREAD, min(UPRIGHT_ANGLE + MAX_BRANCH_SPREAD, bearing))


def _child(
    parent: Node,
    angle: float,
    axis_angle: float,
    length: float,
    step_index: int,
    order: int,
    node_id: int,
) -> Node:
    """Create a new tip node one internode away from ``parent`` along ``angle``."""
    radians = math.radians(angle)
    return Node(
        id=node_id,
        parent_id=parent.id,
        x=parent.x + length * math.cos(radians),
        y=parent.y + length * math.sin(radians),
        angle=angle,
        birth_step=step_index,
        order=order,
        state=NodeState.TIP,
        axis_angle=axis_angle,
    )


def _capacity(genome: Genome) -> int:
    """Crown carrying capacity (max active tips) for a genome, from its vigour."""
    return max(MIN_CAPACITY, round(BASE_CAPACITY * genome.vigor))


def author_breadth(presence_weights: Iterable[float]) -> float:
    """Return how many-voiced a channel's recent activity is, in ``[0, 1]``.

    ``presence_weights`` are each distinct author's current presence weight,
    already decayed to now by the caller (``bot.py``, mirroring how
    ``GuildState.moisture`` is decayed lazily rather than on write) — see
    :data:`AUTHOR_PRESENCE_HALF_LIFE_SECONDS`. An author only counts once their
    weight has reached :data:`AUTHOR_PRESENCE_FLOOR`; the count of qualifying
    authors then saturates at :data:`BREADTH_SATURATION_VOICES`. Pure: no clock,
    no I/O — pass in whatever weights the caller already has.
    """
    voices = sum(1 for weight in presence_weights if weight >= AUTHOR_PRESENCE_FLOOR)
    return _clamp01(voices / BREADTH_SATURATION_VOICES)


def day_bucket(timestamp: float) -> int:
    """Return the whole-UTC-day bucket a Unix ``timestamp`` falls into.

    Pure integer division, exposed as a function so ``bot.py`` and this module
    agree on exactly the same bucketing without either reading a clock: the
    caller always supplies the timestamp.
    """
    return int(timestamp // 86400)


def temporal_rhythm(daily_counts: Sequence[int]) -> float:
    """Return how evenly ``daily_counts`` spreads activity across days, in ``[0, 1]``.

    ``daily_counts`` is one message total per calendar day across
    :data:`RHYTHM_WINDOW_DAYS` consecutive days ending today, zero-filled by the
    caller (``bot.py``) for days with no messages at all — silence is a data
    point, not a gap. The measure is the Gini coefficient of that list, inverted
    so ``1.0`` is a channel whose daily count barely varies and ``0.0`` is one
    where activity concentrates on a handful of days and falls silent the rest
    (a "weekend spikes, otherwise silent" channel).

    Gini reads the *shape* of the distribution, not its size: it is invariant to
    scaling every count by the same factor, so a burst that dumps ten messages
    into one day or ten thousand scores identically low — there is no volume
    that buys steadiness, only genuine spread across real days (see
    ``tests/test_rhythm.py``). Below :data:`RHYTHM_MIN_ACTIVE_DAYS` active days
    in the window there is not enough signal to trust, so this returns
    :data:`NEUTRAL_RHYTHM` instead of an extreme score produced by noise.

    Pure: no clock, no I/O — the caller already holds whatever window it wants
    read.
    """
    active_days = sum(1 for count in daily_counts if count > 0)
    total = sum(daily_counts)
    if active_days < RHYTHM_MIN_ACTIVE_DAYS or total == 0:
        return NEUTRAL_RHYTHM
    n = len(daily_counts)
    ordered = sorted(daily_counts)
    weighted_sum = sum((rank + 1) * count for rank, count in enumerate(ordered))
    gini = (2 * weighted_sum) / (n * total) - (n + 1) / n
    return _clamp01(1.0 - gini)


def thread_qualifies(
    participant_message_counts: Iterable[int], first_message_at: float, last_message_at: float
) -> bool:
    """Whether one thread's accumulated activity is a genuine, sustained side
    conversation rather than a monologue or an abandoned stub.

    ``participant_message_counts`` is each distinct author's message count in
    the thread; ``first_message_at``/``last_message_at`` are the Unix
    timestamps of its first and most recent message (the caller, ``bot.py``,
    anchors ``first_message_at`` at thread creation when it can — see
    ``on_thread_create`` — so a thread that sat open and silent before anyone
    replied is not judged by only the span since that late first reply).
    Requires at least :data:`THREAD_MIN_PARTICIPANTS` distinct people who have
    each posted at least :data:`THREAD_MIN_MESSAGES_PER_PARTICIPANT` times — a
    single extra message from an otherwise-silent second account does not
    qualify a thread — and a real span of at least
    :data:`THREAD_MIN_SPAN_SECONDS` between its first and latest message, so a
    burst posted within the same instant does not either. Pure: the caller
    supplies whatever counts and timestamps it has accumulated; see also
    :func:`thread_depth`, which reads how many currently-live threads clear
    this bar.
    """
    engaged = sum(
        1 for count in participant_message_counts if count >= THREAD_MIN_MESSAGES_PER_PARTICIPANT
    )
    if engaged < THREAD_MIN_PARTICIPANTS:
        return False
    return (last_message_at - first_message_at) >= THREAD_MIN_SPAN_SECONDS


def thread_depth(qualifying_threads: int) -> float:
    """Return how much of the channel's recent life branches into sustained,
    multi-voice threads, in ``[``:data:`NEUTRAL_THREAD_DEPTH`` , 1.0]``.

    ``qualifying_threads`` is how many threads the caller (``bot.py``, via
    its own per-guild aggregation) currently counts as both having cleared
    :func:`thread_qualifies` at some point in their life and still having had
    a message within :data:`THREAD_RECENCY_SECONDS` of now. Saturates at
    :data:`THREAD_DEPTH_SATURATION_THREADS`. Zero qualifying threads returns
    the neutral default rather than an extreme — see
    :data:`NEUTRAL_THREAD_DEPTH`'s docstring for why. Pure: no clock, no I/O.
    """
    if qualifying_threads <= 0:
        return NEUTRAL_THREAD_DEPTH
    saturation = _clamp01(qualifying_threads / THREAD_DEPTH_SATURATION_THREADS)
    return NEUTRAL_THREAD_DEPTH + saturation * (1.0 - NEUTRAL_THREAD_DEPTH)


def voice_is_audible(
    *, connected: bool, muted: bool, deafened: bool, in_afk_channel: bool
) -> bool:
    """Whether one person's voice state counts as being genuinely in the room.

    Being *connected* to a voice channel is not the same as being part of what
    happens in it. Someone muted contributes nothing anyone can hear, someone
    deafened is not even listening, and someone parked in the guild's designated
    AFK channel has been moved there precisely because they stopped taking part.
    All three read the same as not being connected at all, so idling in voice —
    the cheapest possible way to fake this signal — accumulates nothing.

    ``muted``/``deafened`` are meant to cover both the self-set and the
    server-set flag: the caller (``bot.py``) ORs each pair before calling. Pure:
    the caller supplies the flags it read off the gateway event.
    """
    return connected and not muted and not deafened and not in_afk_channel


def shared_voice_seconds(audible_count: int, elapsed_seconds: float) -> float:
    """Return how much of an interval counts as genuine shared voice time.

    ``audible_count`` is how many people were simultaneously audible (per
    :func:`voice_is_audible`) in one voice channel for the whole of
    ``elapsed_seconds``. Below :data:`VOICE_MIN_AUDIBLE` this is zero — not
    discounted, zero: a person alone in a voice channel is not voice activity in
    the sense this signal means, no matter how many hours they sit there, and
    neither is a channel full of muted lurkers. Pure: no clock, no I/O; the
    caller measures the interval and counts the room.
    """
    if audible_count < VOICE_MIN_AUDIBLE:
        return 0.0
    return max(0.0, elapsed_seconds)


def voice_credits(accumulated_seconds: float) -> tuple[int, float]:
    """Split accumulated shared voice time into whole credits and a remainder.

    Returns ``(credits, leftover_seconds)``, where each credit is one
    :data:`VOICE_CREDIT_SECONDS` stretch the caller then puts through the same
    per-person diminishing-returns window a message watering goes through (see
    ``bot.py``). Carrying the remainder forward rather than discarding it is what
    lets several short calls across an evening add up to the same credit a single
    long one would earn, instead of rewarding one unbroken session over the
    ordinary shape of real conversation. Pure.
    """
    if accumulated_seconds < VOICE_CREDIT_SECONDS:
        return 0, max(0.0, accumulated_seconds)
    credits = int(accumulated_seconds // VOICE_CREDIT_SECONDS)
    return credits, accumulated_seconds - credits * VOICE_CREDIT_SECONDS


def root_spread(voice_activity: float) -> float:
    """Map voice activity to how far the plant's root system shows, in ``[0, 1]``.

    ``voice_activity`` is the breadth reading over voice presence weights — the
    same :func:`author_breadth` calculation ``bot.py`` already applies to message
    authors and to reactors, over the people who have sustained genuine shared
    voice time (see the "Voice constants" block above for why it is deliberately
    not recalibrated).

    The curve is the whole design of this dimension, and it is deliberately not
    linear. Below :data:`VOICE_ROOT_THRESHOLD` the result is exactly ``0.0``, so
    a server that never uses voice — and equally a server where two people call
    each other every day — renders precisely as it did before this signal
    existed; absence is an abstention, never a penalty, the same reading
    :data:`NEUTRAL_THREAD_DEPTH` gets for never having used threads. Above the
    threshold the remaining range is raised to :data:`VOICE_ROOT_EXPONENT`, so
    the emergence starts almost imperceptibly and only becomes clearly legible
    near saturation: with the constants as they stand, four sustained voices
    yield about a tenth of full spread, five about four tenths, and only six
    the whole of it.

    Because every root visual in ``render.py`` is additive on top of ``0.0``,
    "no voice activity" is not merely calibrated to look like the old behaviour
    — it *is* the old behaviour, in the same forced way :func:`_depth_exponent`
    returns exactly ``1.0`` below its own neutral point. Pure.
    """
    activity = _clamp01(voice_activity)
    if activity <= VOICE_ROOT_THRESHOLD:
        return 0.0
    beyond = (activity - VOICE_ROOT_THRESHOLD) / (1.0 - VOICE_ROOT_THRESHOLD)
    return beyond ** VOICE_ROOT_EXPONENT


def _jitter_multiplier(rhythm: float) -> float:
    """Scale factor temporal rhythm applies to a new internode's angle noise.

    Linear between :data:`RHYTHM_JITTER_MULTIPLIER_MAX` (a heavily bursty
    channel, at rhythm ``0.0``) and :data:`RHYTHM_JITTER_MULTIPLIER_MIN` (a
    perfectly steady one, at rhythm ``1.0``), with ``1.0`` — no effect at all —
    at ``rhythm == 0.5`` (:data:`NEUTRAL_RHYTHM`).
    """
    rhythm = _clamp01(rhythm)
    return RHYTHM_JITTER_MULTIPLIER_MAX - rhythm * (
        RHYTHM_JITTER_MULTIPLIER_MAX - RHYTHM_JITTER_MULTIPLIER_MIN
    )


def _depth_exponent(thread_depth: float) -> float:
    """Scale factor thread depth applies to the branch-order decay's exponent.

    ``1.0`` — no effect at all, :data:`BRANCH_ORDER_DECAY`'s exact pre-Phase-16
    behaviour — at and below :data:`NEUTRAL_THREAD_DEPTH` (see that constant's
    docstring for why "no sustained thread activity" is never punished below
    the ordinary baseline). Above neutral it falls linearly to
    :data:`DEPTH_ORDER_EXPONENT_MIN` as ``thread_depth`` approaches ``1.0``, so
    ``BRANCH_ORDER_DECAY ** (order * exponent)`` quenches branch chance more
    slowly with every order of nesting — a deep branch structure persists to
    higher orders instead of flattening out near the trunk. Applied only
    through the exponent's *scale on order*, so at ``order == 0`` (the trunk)
    it has no effect whatsoever — a different, independent knob from author
    breadth's flat per-order :func:`_branch_multiplier`.
    """
    depth = _clamp01(thread_depth)
    if depth <= NEUTRAL_THREAD_DEPTH:
        return 1.0
    spent = (depth - NEUTRAL_THREAD_DEPTH) / (1.0 - NEUTRAL_THREAD_DEPTH)
    return 1.0 - spent * (1.0 - DEPTH_ORDER_EXPONENT_MIN)


def _branch_multiplier(breadth: float) -> float:
    """Scale factor author breadth applies to a tip's branch chance.

    Linear between :data:`BREADTH_BRANCH_MULTIPLIER_MIN` (a single dominant
    voice) and :data:`BREADTH_BRANCH_MULTIPLIER_MAX` (a saturated crowd), with
    ``1.0`` — no effect at all — at ``breadth == 0.5``.
    """
    breadth = _clamp01(breadth)
    return BREADTH_BRANCH_MULTIPLIER_MIN + breadth * (
        BREADTH_BRANCH_MULTIPLIER_MAX - BREADTH_BRANCH_MULTIPLIER_MIN
    )


def _grow_tip(
    tip: Node,
    nodes: list[Node],
    genome: Genome,
    step_index: int,
    terminate_chance: float,
    branch_multiplier: float,
    jitter_multiplier: float,
    depth_exponent: float,
    rng: random.Random,
) -> list[int]:
    """Advance one active tip by one step, mutating the working ``nodes`` list.

    The tip always lignifies. With probability ``terminate_chance`` (only nonzero
    once the crown is over capacity) it caps off there — no continuation — trimming
    the crown. Otherwise it puts out a continuation carrying the same axis bearing
    and, with a probability that decays with branch order, a side branch that sets
    out on a bearing of its own and keeps it. New node ids continue the sequence,
    preserving the ``id == index`` invariant. Returns the ids of any new tip nodes
    created (0, 1 or 2), so the caller can extend its active-tips cache without
    rescanning the body for them. ``jitter_multiplier`` (see
    :func:`_jitter_multiplier`) scales every angle drawn this call — temporal
    rhythm's effect, applied independently of ``branch_multiplier``'s.
    ``depth_exponent`` (see :func:`_depth_exponent`) scales how the branch
    chance's per-order decay falls off — thread depth's effect, independent of
    both.
    """
    nodes[tip.id] = replace(tip, state=NodeState.WOODY)
    if rng.random() < terminate_chance:
        return []  # capped off: this branch has a finished, lignified end

    base_length = genome.internode_length * (LENGTH_ORDER_DECAY ** tip.order)

    def internode() -> float:
        return base_length * (1.0 + rng.uniform(-LENGTH_JITTER, LENGTH_JITTER))

    new_tip_ids: list[int] = []

    continuation_angle = _nudged_angle(tip.angle, tip.axis_angle, genome, rng, jitter_multiplier)
    continuation = _child(
        tip, continuation_angle, tip.axis_angle, internode(), step_index, tip.order, len(nodes)
    )
    nodes.append(continuation)
    new_tip_ids.append(continuation.id)

    branch_chance = genome.branch_probability * branch_multiplier * (
        BRANCH_ORDER_DECAY ** (tip.order * depth_exponent)
    )
    if tip.order < MAX_ORDER and rng.random() < branch_chance:
        side = 1.0 if rng.random() < 0.5 else -1.0
        bearing = _limb_bearing(tip.axis_angle, side, genome)
        lateral_angle = _nudged_angle(bearing, bearing, genome, rng, jitter_multiplier)
        lateral = _child(
            tip, lateral_angle, bearing, internode(), step_index, tip.order + 1, len(nodes)
        )
        nodes.append(lateral)
        new_tip_ids.append(lateral.id)

    return new_tip_ids


def _children_map(nodes: list[Node]) -> dict[int, list[int]]:
    """Map each node id to the ids of its children (empty for a leaf/tip)."""
    children: dict[int, list[int]] = {}
    for node in nodes:
        if node.parent_id is not None:
            children.setdefault(node.parent_id, []).append(node.id)
    return children


def _living_frontier(nodes: list[Node], children: dict[int, list[int]]) -> list[Node]:
    """Return the living nodes at the outer edge of living tissue.

    A node is on the frontier if it is alive (``TIP`` or ``WOODY``) and every one
    of its children is already ``DEAD`` — a tip, having no children, always
    qualifies. Recomputed each dieback step, this frontier marches inward: the
    outermost tips die first, then the wood they fed becomes exposed and dies next.
    """
    frontier: list[Node] = []
    for node in nodes:
        if node.state is NodeState.DEAD:
            continue
        kids = children.get(node.id, ())
        if all(nodes[k].state is NodeState.DEAD for k in kids):
            frontier.append(node)
    return frontier


def _growth_step(
    nodes: list[Node],
    genome: Genome,
    seed: int,
    extension_chance: float,
    capacity: int,
    step_index: int,
    active_tips: list[int],
    branch_multiplier: float,
    jitter_multiplier: float,
    depth_exponent: float,
) -> list[int]:
    """Apply one growth step: living tips may extend, branch, or cap off.

    Iterates only ``active_tips`` — the node ids currently in :attr:`NodeState.TIP`
    — instead of rediscovering them by scanning all of ``nodes``, since the crown's
    tip count stays bounded by ``capacity`` however large the accumulated body
    grows. Returns the next step's active tip ids: dormant tips keep their
    relative order, and newly created tips are appended after them — exactly what
    a fresh scan of ``nodes`` would produce, since every id created this step is
    higher than every id already in ``active_tips``. ``branch_multiplier`` (see
    :func:`_branch_multiplier`) scales every tip's branch chance this step —
    author breadth's only effect on growth. ``jitter_multiplier`` (see
    :func:`_jitter_multiplier`) scales every tip's angle-noise amplitude this step
    — temporal rhythm's only effect, independent of ``branch_multiplier``'s.
    ``depth_exponent`` (see :func:`_depth_exponent`) scales how fast branch
    chance decays with order this step — thread depth's only effect, independent
    of both the others.
    """
    # The termination pressure is sampled once per step from the crown size at its
    # start, so it does not depend on the order tips are visited within the step,
    # and it is zero until the crown exceeds capacity.
    overshoot = max(0, len(active_tips) - capacity) / capacity
    terminate_chance = min(MAX_TERMINATION, OVERCAPACITY_PRESSURE * overshoot)
    dormant: list[int] = []
    grown: list[int] = []
    for tip_id in active_tips:
        tip = nodes[tip_id]
        rng = random.Random(f"{seed}:{tip.id}:{step_index}")
        if rng.random() >= extension_chance:
            dormant.append(tip_id)  # dormant this step; may grow in a later one
            continue
        grown.extend(
            _grow_tip(
                tip, nodes, genome, step_index, terminate_chance,
                branch_multiplier, jitter_multiplier, depth_exponent, rng,
            )
        )
    return dormant + grown


def _dieback_step(nodes: list[Node], seed: int, vitality: float, step_index: int) -> None:
    """Apply one dieback step: the exposed living frontier may die (turn ``DEAD``).

    The chance each exposed end dies scales with how far vitality has fallen below
    :data:`DIEBACK_MOISTURE_THRESHOLD`, so a deeper, longer drought kills more and
    reaches further in. Dead wood is never removed and never revives — it stays a
    scar — so a drought is permanently legible in the body. A drought that never
    lifts reaches the very base and kills the whole plant (see :func:`is_dead`);
    only a germ that has *never grown* is spared, lying dormant as a seed rather
    than dying, so an unwatered fresh sprout waits for water instead of dying on
    the spot.
    """
    severity = _clamp01((DIEBACK_MOISTURE_THRESHOLD - vitality) / DIEBACK_MOISTURE_THRESHOLD)
    death_chance = DIEBACK_MAX_RATE * severity ** DIEBACK_EXPONENT
    if death_chance <= 0.0:
        return
    children = _children_map(nodes)
    for node in _living_frontier(nodes, children):
        if node.id == 0 and not children.get(0):
            continue  # a germ that never grew is a dormant seed, not a dying plant
        rng = random.Random(f"dieback:{seed}:{node.id}:{step_index}")
        if rng.random() < death_chance:
            nodes[node.id] = replace(node, state=NodeState.DEAD)


def _bloom_intensity(reaction_warmth: float) -> float:
    """Map accumulated reaction warmth (``[0, 1]``, see :func:`author_breadth`)
    to the vividness a bloom opens with.

    Linear between :data:`BLOOM_INTENSITY_FLOOR` (no reaction warmth at all) and
    ``1.0`` (saturated, broad-based warmth), so a quiet-but-healthy channel still
    gets a real bloom — just a modest one — and no reaction activity is ever
    worth zero.
    """
    return BLOOM_INTENSITY_FLOOR + _clamp01(reaction_warmth) * (1.0 - BLOOM_INTENSITY_FLOOR)


def _milestone_step(stats: LifeStats, size: int, vitality: float, reaction_warmth: float) -> LifeStats:
    """Advance the life statistics by one step: bank health, flower, spend reserve.

    A healthy step banks one unit of reserve. If that leaves the plant in bloom it
    flowers — counting a new flowering when this is the first step of one — and
    pays :data:`BLOOM_COST` out of the bank, which is more than health puts in. So
    a bloom always drains itself and ends, and the plant has to earn the next one.

    ``reaction_warmth`` is read only on the step a bloom *begins*: that single
    sample becomes :attr:`LifeStats.bloom_intensity` and is then carried unchanged
    through every later step of the same bloom (see :func:`_bloom_intensity`) —
    reacting more once a bloom is already open cannot brighten it retroactively,
    and there is no per-step value to watch and time against.
    """
    healthy_steps = stats.healthy_steps + (1 if vitality >= BLOOM_VITALITY else 0)
    blooming = _bloom_state(size, healthy_steps, stats.in_bloom, vitality)
    if not blooming:
        return replace(stats, healthy_steps=healthy_steps, in_bloom=False)
    new_bloom = not stats.in_bloom
    intensity = _bloom_intensity(reaction_warmth) if new_bloom else stats.bloom_intensity
    return LifeStats(
        healthy_steps=max(0, healthy_steps - BLOOM_COST),
        bloom_steps=stats.bloom_steps + 1,
        bloom_count=stats.bloom_count + (1 if new_bloom else 0),
        in_bloom=True,
        bloom_intensity=intensity,
    )


def _mature_limb(nodes: list[Node], host_seed: int, age: int) -> Node | None:
    """Pick the old limb an epiphyte takes hold on, or ``None`` if there is none.

    Eligible wood is living, is a branch rather than the main axis, grew in the
    early part of the host's life, and sits well up in the crown. Of that, the
    lowest branch order is preferred — the tree's heavy limbs, not its fine twigs —
    and the choice among those is seeded by the host, so a given tree always carries
    its epiphyte in one place.
    """
    cutoff = age * EPIPHYTE_HOST_MATURITY
    heights = [node.y for node in nodes]
    floor = min(heights) + (max(heights) - min(heights)) * EPIPHYTE_HOST_MIN_HEIGHT
    eligible = [
        node
        for node in nodes
        if node.state is NodeState.WOODY
        and node.order >= 1
        and node.birth_step <= cutoff
        and node.y >= floor
    ]
    if not eligible:
        return None
    lowest = min(node.order for node in eligible)
    limbs = [node for node in eligible if node.order == lowest]
    return random.Random(f"epiphyte-host:{host_seed}").choice(limbs)


def _settle_epiphyte(nodes: list[Node], host_seed: int, age: int) -> Epiphyte | None:
    """Germinate an epiphyte on the host's oldest heavy limb, if it has one."""
    limb = _mature_limb(nodes, host_seed, age)
    if limb is None:
        return None
    return Epiphyte(host_node_id=limb.id, structure=germinate(_epiphyte_seed(host_seed)))


def _advance_epiphyte(
    epiphyte: Epiphyte, host_seed: int, vitality: float, extension_chance: float
) -> Epiphyte:
    """Advance the epiphyte one step under its host's vitality — it shares the weather.

    It grows and dies back by exactly the same rules as any plant, keyed by its own
    seed and its own age, only far slower — but it accumulates no milestones of its
    own: an epiphyte never blooms and never carries an epiphyte in turn. It also
    does not inherit the host channel's author breadth, temporal rhythm or thread
    depth: it is a passenger on one limb, not itself a reading of the server's
    crowd, cadence or conversation shape, so its branching, its angle noise and
    its order decay always use the neutral multiplier (as if breadth, rhythm and
    thread depth were exactly their neutral midpoints).
    """
    genome = epiphyte_genome(host_seed)
    body = epiphyte.structure
    nodes = list(body.nodes)
    active_tips = list(body.active_tips)
    if vitality < DIEBACK_MOISTURE_THRESHOLD:
        _dieback_step(nodes, body.seed, vitality, body.step_count)
        active_tips = [tid for tid in active_tips if nodes[tid].state is NodeState.TIP]
    else:
        active_tips = _growth_step(
            nodes,
            genome,
            body.seed,
            extension_chance * EPIPHYTE_PACE,
            _capacity(genome),
            body.step_count,
            active_tips,
            1.0,
            1.0,
            1.0,
        )
    return replace(
        epiphyte,
        structure=replace(
            body, nodes=tuple(nodes), step_count=body.step_count + 1, active_tips=tuple(active_tips)
        ),
    )


def grow(
    structure: Structure,
    genome: Genome,
    moisture: float,
    steps: int,
    breadth: float = 0.5,
    rhythm: float = 0.5,
    reaction_warmth: float = 0.0,
    thread_depth: float = NEUTRAL_THREAD_DEPTH,
) -> Structure:
    """Return the structure advanced ``steps`` life-steps under ``moisture`` (pure).

    Each step runs one of two regimes, chosen by the vitality that ``moisture``
    gates:

    * **Growth** (vitality at or above :data:`DIEBACK_MOISTURE_THRESHOLD`): every
      living tip may extend, branch, or cap off. The chance a tip extends scales
      with moisture — brisk when wet, almost nothing when barely healthy — and the
      crown self-limits at its carrying capacity. This is the honest signal.
      ``breadth`` (see :func:`author_breadth`), how many distinct people the
      channel's recent activity comes from, additionally scales how often a tip
      forks rather than merely extends (:func:`_branch_multiplier`) — many
      voices grow a wider, more branched crown; one dominant voice grows a
      narrower, straighter one. It defaults to ``0.5``, the neutral point with
      no effect at all, so a caller that does not pass it reproduces the exact
      growth this function always produced. ``rhythm`` (see
      :func:`temporal_rhythm`), how evenly that activity is spread across days
      rather than who it comes from, independently scales the organic angle
      noise applied to every new internode (:func:`_jitter_multiplier`) — a
      steady daily cadence calms the body into a more symmetric shape, a bursty
      one grows a more irregular, gnarled one — at the same size and the same
      branching ``breadth`` alone would have produced, since it scales a
      different, independent knob. It defaults to ``0.5`` for the same reason
      ``breadth`` does. ``thread_depth`` (see :func:`thread_depth`), how much of
      the channel's recent activity spins off into sustained, multi-voice
      threads, independently scales how far branch chance persists into higher
      orders rather than quenching near the trunk (:func:`_depth_exponent`) —
      a third, independent knob again: a channel heavy on sustained threads
      grows a more deeply nested branch structure at the same size and the same
      crown breadth and body regularity ``breadth`` and ``rhythm`` alone would
      have produced. It defaults to :data:`NEUTRAL_THREAD_DEPTH`, again the
      neutral point with no effect.
    * **Dieback** (vitality below the threshold): the plant is parched, so instead
      of growing it dies back from the outside in. Dead wood stays in the body
      forever, a permanent scar of the drought.

    Either way each step also advances the plant's life statistics, which is where
    the milestones come from: health is banked and spent by flowering, and a tree
    that has grown old and large and flowered often enough takes on an epiphyte,
    which from then on grows alongside it under the same weather. ``reaction_warmth``
    (how broadly, not how loudly, the channel has reacted recently — the same
    breadth reading as ``breadth`` above, just over reactors instead of message
    authors) plays no part in growth, branching or dieback at all: it is read once,
    only on the step a bloom begins, and becomes that bloom's fixed vividness (see
    :func:`_bloom_intensity`). It defaults to ``0.0``, the floor: a caller that does
    not pass it gets the most modest bloom rather than a denied one.

    So the number of dead nodes only ever rises, and lignified wood (living plus
    dead) never falls: the body accumulates monotonically and remembers its whole
    life. Decisions are seeded by ``(seed, node_id, step_index)``, so this is
    deterministic and chunk-invariant — the same total steps produce the same
    result whether run at once or one at a time. The input is never mutated.
    """
    vitality = _clamp01(moisture)
    extension_chance = vitality * EXTENSION_RATE
    capacity = _capacity(genome)
    branch_multiplier = _branch_multiplier(breadth)
    jitter_multiplier = _jitter_multiplier(rhythm)
    depth_exponent = _depth_exponent(thread_depth)
    parched = vitality < DIEBACK_MOISTURE_THRESHOLD
    nodes = list(structure.nodes)
    active_tips = list(structure.active_tips)
    step_index = structure.step_count
    stats = structure.stats
    epiphyte = structure.epiphyte

    for _ in range(max(0, steps)):
        if parched:
            _dieback_step(nodes, structure.seed, vitality, step_index)
            active_tips = [tid for tid in active_tips if nodes[tid].state is NodeState.TIP]
        else:
            active_tips = _growth_step(
                nodes,
                genome,
                structure.seed,
                extension_chance,
                capacity,
                step_index,
                active_tips,
                branch_multiplier,
                jitter_multiplier,
                depth_exponent,
            )
        stats = _milestone_step(stats, len(nodes), vitality, reaction_warmth)
        step_index += 1

        if epiphyte is not None:
            epiphyte = _advance_epiphyte(epiphyte, structure.seed, vitality, extension_chance)
        elif _epiphyte_conditions_met(step_index, len(nodes), stats.bloom_count):
            epiphyte = _settle_epiphyte(nodes, structure.seed, step_index)

    return Structure(
        nodes=tuple(nodes),
        step_count=step_index,
        seed=structure.seed,
        generation=structure.generation,
        parent_seed=structure.parent_seed,
        lineage_blooms=structure.lineage_blooms,
        stats=stats,
        epiphyte=epiphyte,
        active_tips=tuple(active_tips),
    )


def serialize(structure: Structure) -> dict:
    """Return a JSON-serialisable dict fully describing ``structure`` (pure).

    An epiphyte is nested as a structure of its own, since that is exactly what it
    is.
    """
    return {
        "seed": structure.seed,
        "step_count": structure.step_count,
        "generation": structure.generation,
        "parent_seed": structure.parent_seed,
        "lineage_blooms": structure.lineage_blooms,
        "stats": {
            "healthy_steps": structure.stats.healthy_steps,
            "bloom_steps": structure.stats.bloom_steps,
            "bloom_count": structure.stats.bloom_count,
            "in_bloom": structure.stats.in_bloom,
            "bloom_intensity": structure.stats.bloom_intensity,
        },
        "epiphyte": (
            None
            if structure.epiphyte is None
            else {
                "host_node_id": structure.epiphyte.host_node_id,
                "structure": serialize(structure.epiphyte.structure),
            }
        ),
        "nodes": [
            {
                "id": node.id,
                "parent_id": node.parent_id,
                "x": node.x,
                "y": node.y,
                "angle": node.angle,
                "birth_step": node.birth_step,
                "order": node.order,
                "state": node.state.value,
                "axis_angle": node.axis_angle,
            }
            for node in structure.nodes
        ],
    }


def deserialize(data: dict) -> Structure:
    """Rebuild a :class:`Structure` from :func:`serialize`'s output (pure).

    Fields added by a later phase default to their fresh values, so a plant stored
    before those phases loads as one that has simply not reached them yet.
    """
    stats = data.get("stats", {})
    epiphyte = data.get("epiphyte")
    nodes = tuple(
        Node(
            id=entry["id"],
            parent_id=entry["parent_id"],
            x=entry["x"],
            y=entry["y"],
            angle=entry["angle"],
            birth_step=entry["birth_step"],
            order=entry["order"],
            state=NodeState(entry["state"]),
            # Nodes stored before limbs held a bearing keep growing along their own.
            axis_angle=entry.get("axis_angle", entry["angle"]),
        )
        for entry in data["nodes"]
    )
    return Structure(
        nodes=nodes,
        step_count=data["step_count"],
        seed=data["seed"],
        generation=data.get("generation", 1),
        parent_seed=data.get("parent_seed"),
        lineage_blooms=data.get("lineage_blooms", 0),
        # Not stored: derived once here from the loaded nodes, then kept
        # incrementally by grow() for the rest of this structure's life.
        active_tips=tuple(node.id for node in nodes if node.state is NodeState.TIP),
        stats=LifeStats(
            healthy_steps=stats.get("healthy_steps", 0),
            bloom_steps=stats.get("bloom_steps", 0),
            bloom_count=stats.get("bloom_count", 0),
            in_bloom=stats.get("in_bloom", False),
            # A plant saved before this field existed but already mid-bloom gets
            # the floor rather than 0.0 — an already-open bloom stored with no
            # intensity on record should not render as though it earned nothing.
            bloom_intensity=stats.get(
                "bloom_intensity", BLOOM_INTENSITY_FLOOR if stats.get("in_bloom", False) else 0.0
            ),
        ),
        epiphyte=(
            None
            if epiphyte is None
            else Epiphyte(
                host_node_id=epiphyte["host_node_id"],
                structure=deserialize(epiphyte["structure"]),
            )
        ),
    )
