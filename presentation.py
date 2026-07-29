"""How the plant is framed: the shape and the colour of the message around it.

Pure logic. No side effects, no clock reads, no ``import discord`` and no Pillow —
this module decides *what the container looks like* and hands back a plain
:class:`Panel`, which the adapter pours into a ``discord.Embed``. That split is
the same one :mod:`voice` already makes: the interesting decision is testable
without Discord, and ``bot.py`` keeps only the four lines that know what an embed
is.

The module composes **two** panels, and the split between them is the design:

:func:`compose` builds the *ambient* panel — the one the living channel message
wears, rebuilt every heartbeat, seen by everyone in the server whether they asked
or not. It is the plant's face and nothing else: a full-size picture, the plant's
own words, an accent colour read from its condition, and the quiet footer. It
carries no instruments at all. Nobody scrolling past a channel asked to read a
gauge, and a number beside the picture is the one thing guaranteed to be looked at
instead of it.

:func:`compose_instruments` builds the *readings* panel, which exists only behind
a button on ``/plant`` — asked for, per invocation, by one person, and seen by
nobody else. Every instrument the module has ever built lives there, all of them
at once, in the plain register the persona bible reserves for readouts.

Three ideas carry both, and they mirror the ones the plant itself is built on:

**The frame is derived, never configured.** Accent colour, which instruments
apply and image placement are all read out of the plant's current state — the same
state :mod:`voice` reads. There is no theme, no setting and no command that
changes any of it, exactly as there is none that changes the plant's own
appearance. Which of the two panels you are looking at is a momentary choice, not
a stored preference: it changes nothing for the next viewer, and the ambient
message has no toggle at all.

**One life event, one shape.** :func:`life_event` collapses the plant's condition
into a single :class:`LifeEvent`, which decides the ambient panel's colour and its
words, and decides in :func:`_fields` which instruments an event is *about* — the
per-event rows that the readings panel is assembled out of. The ordering in
:func:`life_event` is the whole design decision: endings and beginnings outrank
what is happening to the body, which outranks what the body has become, which
outranks the ordinary day.

**A quiet constant underneath.** The footer is the one element whose shape never
changes, and it is on both panels: a seed-derived sigil, the generation, the age
in days, and whichever permanent marks the plant carries. Lineage and age live
down there, which is exactly what lets the ambient panel above it carry nothing.

The boundary this module must not cross: it frames the rendered image, it never
touches it. Everything inside the PNG — the body, the palette, the foliage,
the blossoms — belongs to :mod:`render` alone. That holds for the cross-section
too: :data:`LifeEvent.RINGS` decides that the message is about the record and
what shape it takes, while what a ring looks like is ``render.render_rings``'s
alone. See "Präsentation" in ``CLAUDE.md``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

import moisture
import structure
import voice

#: Seconds in a day — a growth step is a constant real duration (see ``CLAUDE.md``,
#: "Zeitmodell"), so a step count converts honestly into days for display.
_DAY_SECONDS: float = 24 * 60 * 60


class LifeEvent(Enum):
    """The single thing the plant is currently doing, as far as framing cares.

    Deliberately coarser than :class:`voice.Mood`: the voice needs eight moods to
    have something distinct to *say* about each, while the frame needs only as
    many shapes as are genuinely worth designing apart. Resolved in the fixed
    order documented on :func:`life_event`.
    """

    GERMINATION = "germination"
    REBIRTH = "rebirth"
    RINGS = "rings"
    DIEBACK = "dieback"
    BLOOM = "bloom"
    DROUGHT = "drought"
    THIRST = "thirst"
    EPIPHYTE = "epiphyte"
    FLOURISHING = "flourishing"
    STEADY = "steady"
    DEATH = "death"


class ImagePlacement(Enum):
    """Where the already-rendered plant image sits in the frame.

    Purely a slot in the message — the PNG itself is identical either way, which
    is what lets the two panels swap it between slots on a button press without
    re-rendering or re-uploading anything.

    The two values now line up exactly with the two panels rather than with life
    events: the ambient panel is *always* :data:`FULL`, on every event without
    exception, because that panel exists to show the plant; the readings panel is
    always :data:`THUMBNAIL`, because there the numbers lead and the plant is what
    they are about.
    """

    #: Full width, below the text: the picture leads.
    FULL = "full"
    #: Small, top right: the readings lead and the plant accompanies them.
    THUMBNAIL = "thumbnail"


@dataclass(frozen=True)
class Field:
    """One plain readout of the plant — an instrument, never part of its speech.

    Only ever appears on the readings panel (:func:`compose_instruments`). Every
    field carries a short name and a short value and is laid out inline, so a
    readings panel reads as a compact block of gauges rather than a list of
    paragraphs; there is deliberately no width or ordering knob on an individual
    field, because which instruments appear at all is already decided by the
    plant's state rather than by anyone's preference.
    """

    name: str
    value: str


@dataclass(frozen=True)
class Panel:
    """Everything the adapter needs to build the message, and nothing Discord-shaped.

    Used for both panels. On the ambient one, ``title`` and ``body`` are the
    plant's own words, taken from :mod:`voice` unchanged, and ``fields`` is empty
    on every event but the cross-section; on the readings one, ``title`` and
    ``body`` are deliberately plain and ``fields`` is where everything is. Either
    way this module decides where the words sit, never what they say.
    """

    event: LifeEvent
    accent: int
    title: str
    body: str
    fields: tuple[Field, ...]
    image: ImagePlacement
    footer: str


# --- The palette --------------------------------------------------------------
#
# Nord throughout, the same scheme the rendered plant is drawn in (see the colour
# table in CLAUDE.md), so the frame and its picture read as one object. Every
# accent below is a *state*, not a decoration: the colour is another small honest
# expression of the plant's condition, which is why there is no fixed default and
# no Discord blurple anywhere in this file.

#: Deep polar night. A dead plant's frame goes quiet rather than alarming.
DEATH_ACCENT = 0x4C566A
#: Leaf green lifted toward snow: pale, fresh, nothing weathered yet.
GERMINATION_ACCENT = 0xBDCFB0
#: The pale living stem. A successor is new, but cooler than a founder — it comes
#: up in soil that has already held something.
REBIRTH_ACCENT = 0x8FBCBB
#: Aurora red, the palette's one alarm. Reserved for the single state that costs
#: the plant wood it can never grow back.
DIEBACK_ACCENT = 0xBF616A
#: The rooted stem brown of a body running on reserves.
DROUGHT_ACCENT = 0x5E4A3B
#: Warm sand — the first yellowing at the newest leaves, before anything is lost.
THIRST_ACCENT = 0xEBCB8B
#: Aurora purple: a second organism gets a colour that is neither the host's wood
#: nor its foliage.
EPIPHYTE_ACCENT = 0xB48EAD
#: The bud accent, the brightest thing in the scheme: everything open.
FLOURISHING_ACCENT = 0x88C0D0
#: Leaf green — the ordinary, most-seen state, and the baseline the others depart
#: from.
STEADY_ACCENT = 0xA3BE8C
#: Nord snow storm — pale, dry, papery. The one event that is not a condition of
#: the plant but a reading of its record, so it wears the only accent in this
#: module that is not a colour anything living here could be: not leaf, not wood,
#: not flower. It is the colour of a cut surface.
RINGS_ACCENT = 0xD8DEE9

#: The one fixed accent, worn by the operational surfaces (``/help`` and friends).
#: Those deliberately do not track the plant: a moderator reading them is looking
#: for an explanation, not a readout. See "Gesprochen vs. sachlich" in CLAUDE.md.
PLAIN_ACCENT = 0x88C0D0

#: The Nord accents a bloom's colour is drawn from — the same ramp, in the same
#: order, that ``render.BLOOM_RAMP`` paints the blossoms themselves along, so the
#: frame of a flowering plant matches the flowers inside it. Duplicated rather
#: than imported because ``render`` carries Pillow and this module must not.
BLOOM_RAMP: tuple[int, ...] = (0x88C0D0, 0xB48EAD, 0xBF616A, 0xD08770, 0xEBCB8B)
#: Nord snow, and how far a blossom's colour is lifted toward it for the frame.
#: The blossom colours were chosen to carry against the render's dark soil; the
#: accent is a thin stripe read against a message instead, so it takes the same
#: hue a shade lighter. It also keeps a flowering plant's colour clear of every
#: fixed accent below for all 128 values the bloom gene can take, which a raw ramp
#: endpoint would not (see ``tests/test_presentation.py``).
SNOW = 0xECEFF4
BLOOM_LIFT: float = 0.15
#: How far a bloom's accent is lifted toward :data:`SNOW` at the lowest bloom
#: intensity (see ``structure.LifeStats.bloom_intensity``) — reusing the same
#: blend :data:`BLOOM_LIFT` already performs, just carried further, rather than
#: a second colour system: a modest bloom's accent is the same hue, only paler.
BLOOM_LIFT_MODEST: float = 0.4

#: Accent per life event, for every event whose colour is fixed. :data:`LifeEvent.BLOOM`
#: is absent on purpose: a flowering plant's accent is its own (see :func:`accent`).
_EVENT_ACCENTS: dict[LifeEvent, int] = {
    LifeEvent.GERMINATION: GERMINATION_ACCENT,
    LifeEvent.REBIRTH: REBIRTH_ACCENT,
    LifeEvent.RINGS: RINGS_ACCENT,
    LifeEvent.DIEBACK: DIEBACK_ACCENT,
    LifeEvent.DROUGHT: DROUGHT_ACCENT,
    LifeEvent.THIRST: THIRST_ACCENT,
    LifeEvent.EPIPHYTE: EPIPHYTE_ACCENT,
    LifeEvent.FLOURISHING: FLOURISHING_ACCENT,
    LifeEvent.STEADY: STEADY_ACCENT,
    LifeEvent.DEATH: DEATH_ACCENT,
}

#: Plain label per moisture stage, for the ``Stage`` instrument.
STAGE_LABELS: dict[moisture.Stage, str] = {
    moisture.Stage.WITHERED: "Withered",
    moisture.Stage.DRY: "Dry",
    moisture.Stage.HEALTHY: "Healthy",
    moisture.Stage.THRIVING: "Thriving",
}

#: The marks a plant's footer sigil is drawn from. An individual's own small
#: typographic signature, chosen from its seed the same deterministic way its
#: words are — so a server recognises its plant by its mark as well as its shape,
#: and a successor, carrying a mutated seed, comes up wearing a new one.
SIGILS: tuple[str, ...] = ("❦", "❧", "❀", "❁", "❃", "❋", "✾", "✽", "✼", "✻", "✺", "✹")

#: Spoken generation numbers, so the footer reads as typography rather than as a
#: counter. Beyond the tenth the plain number takes over — a line that long has
#: earned the right to be stated flatly.
_ORDINALS: tuple[str, ...] = (
    "first", "second", "third", "fourth", "fifth",
    "sixth", "seventh", "eighth", "ninth", "tenth",
)


def _blend(low: int, high: int, t: float) -> int:
    """Linearly interpolate two packed ``0xRRGGBB`` colours; ``t`` is clamped to [0, 1]."""
    t = max(0.0, min(1.0, t))
    blended = 0
    for shift in (16, 8, 0):
        start = (low >> shift) & 0xFF
        end = (high >> shift) & 0xFF
        blended |= round(start + (end - start) * t) << shift
    return blended


def _bloom_accent(seed: int, intensity: float) -> int:
    """The colour this individual flowers in, as a point along :data:`BLOOM_RAMP`.

    Read from the same ``bloom_hue`` gene the renderer paints the blossoms with, so
    the frame of a flowering plant is the colour of its own flowers rather than a
    generic festive one — the one accent in this module that differs per plant,
    lifted toward snow by an amount that runs from :data:`BLOOM_LIFT` (full
    intensity — this bloom's own saturated hue, unchanged from before Phase 15)
    to :data:`BLOOM_LIFT_MODEST` (the intensity floor — the same hue, washed
    pale) as ``intensity`` falls. Reuses the existing ramp and blend rather than
    a second colour axis for vividness.
    """
    hue = max(0.0, min(1.0, structure.genome_from_seed(seed).bloom_hue))
    position = hue * (len(BLOOM_RAMP) - 1)
    stop = min(int(position), len(BLOOM_RAMP) - 2)
    color = _blend(BLOOM_RAMP[stop], BLOOM_RAMP[stop + 1], position - stop)
    lift = BLOOM_LIFT_MODEST - max(0.0, min(1.0, intensity)) * (BLOOM_LIFT_MODEST - BLOOM_LIFT)
    return _blend(color, SNOW, lift)


def life_event(state: voice.VoiceState, showing_rings: bool = False) -> LifeEvent:
    """Collapse the plant's condition into the one event that shapes its frame.

    The order below *is* the design, and it reads in five tiers:

    1. **An ending or a beginning** — death, a founding germination, a successor's
       rebirth. The body's identity has changed, which outranks anything happening
       to it.
    2. **The whole record at once** — the cross-section, shown for one day a year
       (see ``bot.py``'s ``_cross_section``). It ranks under the identity changes
       and over everything else, and both halves of that are deliberate. Under,
       because a plant that is dying or has just begun has a more urgent thing to
       be than retrospective — though in practice the two cannot collide, since a
       dead plant records no year and a successor's rings are wiped. Over, because
       the alternative is worse than it looks: yielding to whatever the weather
       happens to be doing on the turn of the year would cost the plant its one
       showing for a whole further year, on the strength of a drought that will be
       over in a week. The ordinary instruments come along inside the ring row
       instead, so nothing about the present is hidden by showing the past.
    3. **What is happening to it** — dieback, a flowering, drought, thirst. All
       four are time-limited and moving, including the bloom: it drains the very
       reserve that opened it and ends on its own, so it belongs with the changing
       states rather than with the standing ones.
    4. **What it has become** — carrying an epiphyte. Permanent, and therefore
       ranked *below* the passing states: a tree that has become habitat still
       shows its thirst when it is thirsty.
    5. **The ordinary day** — flourishing, or simply steady.

    ``showing_rings`` defaults to ``False``, so a caller that knows nothing about
    the cross-section resolves exactly the events this function always did.
    """
    if state.mood is voice.Mood.DEAD:
        return LifeEvent.DEATH
    if state.mood is voice.Mood.SEEDLING:
        return LifeEvent.GERMINATION
    if state.mood is voice.Mood.REBORN:
        return LifeEvent.REBIRTH
    if showing_rings:
        return LifeEvent.RINGS
    if state.mood is voice.Mood.PARCHED:
        return LifeEvent.DIEBACK
    if state.blooming:
        return LifeEvent.BLOOM
    if state.mood is voice.Mood.WITHERED:
        return LifeEvent.DROUGHT
    if state.mood is voice.Mood.DRY:
        return LifeEvent.THIRST
    if state.hosting:
        return LifeEvent.EPIPHYTE
    if state.mood is voice.Mood.LUSH:
        return LifeEvent.FLOURISHING
    return LifeEvent.STEADY


def accent(event: LifeEvent, seed: int, intensity: float = 1.0) -> int:
    """The frame's colour for this event, as a packed ``0xRRGGBB`` integer.

    Deterministic in its inputs and total over :class:`LifeEvent` — there is no
    fallback colour, because a fallback is exactly the generic default this whole
    module exists to remove. ``intensity`` (see ``structure.LifeStats.bloom_intensity``)
    only ever matters for :data:`LifeEvent.BLOOM`; it defaults to ``1.0`` — full
    saturation, this function's exact pre-Phase-15 behaviour — so every other
    event, and any caller that does not pass it, is unaffected.
    """
    if event is LifeEvent.BLOOM:
        return _bloom_accent(seed, intensity)
    return _EVENT_ACCENTS[event]


# --- The footer: the one thing that never changes shape -----------------------


def sigil(seed: int) -> str:
    """This plant's own typographic mark, drawn from its seed.

    Hashed explicitly rather than with the built-in ``hash()``, whose salt is
    randomised per process — for exactly the reason :func:`voice._index` gives: a
    mark that changed on every restart would be no mark at all.
    """
    digest = hashlib.blake2b(f"{seed}|sigil".encode(), digest_size=8).digest()
    return SIGILS[int.from_bytes(digest, "big") % len(SIGILS)]


def _generation_phrase(generation: int) -> str:
    """Name the plant's place in its line, in words while words stay short."""
    if 1 <= generation <= len(_ORDINALS):
        return f"{_ORDINALS[generation - 1]} generation"
    return f"generation {generation}"


def _age_days(step_count: int, seconds_per_step: float) -> int:
    """Whole days of life a step count stands for.

    A growth step is a constant real duration by design (see ``CLAUDE.md``,
    "Zeitmodell"), so the caller's tick interval converts steps into days without
    this module ever reading a clock.
    """
    return int(step_count * seconds_per_step // _DAY_SECONDS)


def _age_phrase(days: int, dead: bool) -> str:
    """Say the plant's age, or — once it has died — the length of the life it had."""
    if dead:
        return f"lived {days} days" if days else "lived less than a day"
    return f"{days} days" if days else "first day"


def footer(state: voice.VoiceState, plant: structure.Structure, seconds_per_step: float) -> str:
    """Build the quiet line that runs under every event, in the same shape every time.

    Sigil, generation, age, then whichever permanent marks the plant carries. It is
    the only place the generation and the age appear on most events, which is
    precisely what frees the field row above it to differ so much between events —
    the continuity lives down here instead of being restated in every panel.
    """
    parts = [
        sigil(plant.seed),
        _generation_phrase(state.generation),
        _age_phrase(_age_days(plant.step_count, seconds_per_step), state.mood is voice.Mood.DEAD),
    ]
    if state.seeded:
        parts.append("seeded")
    if state.hosting:
        parts.append("hosting an epiphyte")
    return " · ".join(parts)


# --- The field structures: one per event --------------------------------------
#
# Each builder below owns one event's instrument row, and they are meant to be
# read side by side: the differences are the point. Nothing here is a template
# with substituted values — the field *names* and their count change with what the
# plant is going through.
#
# These rows no longer reach the living channel message (the cross-section aside;
# see :func:`compose`). They are now the readings panel's source of truth: it is
# assembled by walking every event's row and taking the union, so "which
# instruments does a flowering plant have" is still answered here, in one place,
# rather than restated in a second list that could drift out of step. An event's
# row remains the honest answer to *what this event is about* — the readings panel
# simply asks all the questions at once.


def _moisture_field(moisture_value: float) -> Field:
    """The one instrument almost every living event shows."""
    return Field("Moisture", f"{moisture_value:.0%}")


def _stage_field(moisture_value: float) -> Field:
    """The named band the moisture falls in — shown only where it adds something."""
    return Field("Stage", STAGE_LABELS[moisture.stage(moisture_value)])


def _age_field(plant: structure.Structure, seconds_per_step: float) -> Field:
    """Age in days rather than in growth steps: a duration a reader already owns."""
    days = _age_days(plant.step_count, seconds_per_step)
    return Field("Age", f"{days} days" if days else "less than a day")


def _dead_wood_field(plant: structure.Structure) -> Field:
    """What the drought has cost so far — the only instrument dieback really has.

    Moisture says how bad the weather is; this says how much of the body is
    already gone for good, which is the part that will still be legible next month.
    """
    lost = sum(1 for node in plant.nodes if node.state is structure.NodeState.DEAD)
    return Field("Wood lost", f"{lost} of {len(plant.nodes)}")


def _lineage_field(plant: structure.Structure) -> Field:
    """What stood here before this one — meaningful at exactly one moment, its rebirth."""
    before = plant.generation - 1
    predecessors = "1 before it" if before == 1 else f"{before} before it"
    flowered = "none flowered" if not plant.lineage_blooms else f"{plant.lineage_blooms} flowered"
    return Field("Its line", f"{predecessors} · {flowered}")


def _crown_field(plant: structure.Structure) -> Field:
    """How much of the plant is actively pushing — worth showing only when it is.

    On a soaked plant this is the number that is really moving; on a dry one it
    would just be a small integer sitting next to a large one.
    """
    tips = len(plant.active_tips)
    return Field("Crown", f"{tips} growing tips" if tips != 1 else "1 growing tip")


def _flowerings_field(plant: structure.Structure) -> Field:
    """How many separate times this plant has come into bloom, this one included."""
    count = plant.stats.bloom_count
    return Field("Flowerings", "the first" if count <= 1 else str(count))


def _epiphyte_field(plant: structure.Structure, seconds_per_step: float) -> Field:
    """The passenger's own age — the host is not the only thing living here."""
    if plant.epiphyte is None:
        return Field("Epiphyte", "settling")
    days = _age_days(plant.epiphyte.structure.step_count, seconds_per_step)
    return Field("Epiphyte", f"{days} days old" if days else "newly settled")


def _rings_field(rings: tuple[structure.Ring, ...]) -> Field:
    """How many finished years the cross-section is showing.

    The plant is forbidden from counting its own years out loud (see the persona
    bible), which is exactly what an instrument is for: the words say what the
    wood means, this says how much of it there is.
    """
    count = len(rings)
    return Field("Rings", "1 year" if count == 1 else f"{count} years")


def _scar_rings_field(rings: tuple[structure.Ring, ...]) -> Field:
    """Which of those years cost the plant wood — named, since a ring has a date.

    The one instrument in this module that says something the picture cannot: a
    grey band is legible as *a* bad year, but not as *which*. Reads the same
    ``scarred`` flag :func:`structure.rings` sets from the Phase 7 dieback, so
    this can never disagree with the picture beside it.
    """
    scarred = [ring.year for ring in rings if ring.scarred]
    return Field("Scar rings", " · ".join(str(year) for year in scarred) if scarred else "none")


def _fields(
    event: LifeEvent,
    plant: structure.Structure,
    moisture_value: float,
    seconds_per_step: float,
    rings: tuple[structure.Ring, ...] = (),
) -> tuple[Field, ...]:
    """Return the instrument row for one event — its own, not a shared template.

    Read as a set, the rows say something the individual rows cannot: how much
    there is to measure opens up as the plant does and closes down as it suffers.
    A flourishing plant carries four instruments, an ordinary one three, a thirsty
    one two, a plant in drought a single number, and a germinating or dead one none
    at all — at those two ends there is nothing to measure that the plant has not
    already said better itself.

    The cross-section is the one event whose row is not about the present at all
    — two readings of the record, and the moisture last rather than first, so a
    drought running on the day the rings are shown is still on the panel without
    displacing what the panel is for. It is also the one row :func:`compose` still
    puts on the living message; see there for why that exception survived the
    stripping of every other row.
    """
    if event is LifeEvent.GERMINATION:
        return ()
    if event is LifeEvent.RINGS:
        return (
            _rings_field(rings),
            _scar_rings_field(rings),
            _moisture_field(moisture_value),
        )
    if event is LifeEvent.REBIRTH:
        return (_lineage_field(plant),)
    if event is LifeEvent.DEATH:
        return ()
    if event is LifeEvent.DIEBACK:
        return (_moisture_field(moisture_value), _dead_wood_field(plant))
    if event is LifeEvent.DROUGHT:
        return (_moisture_field(moisture_value),)
    if event is LifeEvent.THIRST:
        return (_moisture_field(moisture_value), _age_field(plant, seconds_per_step))
    if event is LifeEvent.BLOOM:
        return (
            _moisture_field(moisture_value),
            _flowerings_field(plant),
            _age_field(plant, seconds_per_step),
        )
    if event is LifeEvent.EPIPHYTE:
        return (
            _moisture_field(moisture_value),
            _age_field(plant, seconds_per_step),
            _epiphyte_field(plant, seconds_per_step),
        )
    if event is LifeEvent.FLOURISHING:
        return (
            _moisture_field(moisture_value),
            _stage_field(moisture_value),
            _age_field(plant, seconds_per_step),
            _crown_field(plant),
        )
    return (
        _moisture_field(moisture_value),
        _stage_field(moisture_value),
        _age_field(plant, seconds_per_step),
    )


# --- Composition: the ambient panel --------------------------------------------


def compose(
    plant: structure.Structure,
    moisture_value: float,
    seconds_per_step: float,
    rings: tuple[structure.Ring, ...] = (),
) -> Panel:
    """Frame a plant for the living channel message: the picture, and what it says.

    This is the panel nobody asked for. It is rebuilt on every heartbeat and sits
    in a channel people are using for something else, so it carries the plant and
    nothing beside it: a full-size image on every event without exception, the
    plant's own words from :mod:`voice` untouched, an accent read from its
    condition, and the quiet footer. No instrument row — not moisture, not stage,
    not age, not crown, not wood lost. Those all still exist and are all still
    computed here (see :func:`_fields`); they live on the readings panel, which
    somebody has to press a button to see (:func:`compose_instruments`).

    Two consequences of that are worth stating, because both used to be otherwise:
    a germinating or newly reborn plant no longer accompanies its sentence as a
    thumbnail but leads full width like everything else — a seedling being a few
    pixels of thread in a lot of soil is *true*, and the panel that exists to show
    the plant should show it — and a milestone the event is about is no longer
    lifted into a field of its own. Every milestone line the plant carries now
    stays where it was written, in its own words in the body.

    ``seconds_per_step`` is the adapter's tick interval, passed in rather than read
    from a clock or a config so the whole composition stays a pure function of the
    plant.

    ``rings`` is non-empty only while the plant's cross-section is being shown —
    one day a year, decided by the adapter (see ``bot.py``'s ``_cross_section``),
    never by anything here. It is the **one** event that keeps its instrument row,
    and that exception is deliberate rather than overlooked. The cross-section is
    not the plant's face but a reading of its record, and the record is unreadable
    without it: the plant is forbidden from naming its own years out loud (see the
    persona bible), so a grey band is legible as *a* bad year and never as *which*.
    The moisture riding along at the end of that row is Phase 19's own decision,
    made for the same reason it is being kept — the retrospective outranks the
    weather for one day a year, and the moisture reading is what stops that from
    hiding a drought that is running right now.
    """
    state = voice.read_state(plant, moisture_value)
    event = life_event(state, showing_rings=bool(rings))

    if event is LifeEvent.RINGS:
        title, body = voice.ring_title(plant.seed, len(rings)), [voice.ring_passage(plant.seed, len(rings))]
        fields = _fields(event, plant, moisture_value, seconds_per_step, rings)
    else:
        title, body = voice.title(state), [voice.passage(state)]
        fields = ()

    milestones = voice.milestone_lines(state)
    if milestones:
        body.append("\n".join(milestones))

    return Panel(
        event=event,
        accent=accent(event, plant.seed, plant.stats.bloom_intensity),
        title=title,
        body="\n\n".join(body),
        fields=fields,
        image=ImagePlacement.FULL,
        footer=footer(state, plant, seconds_per_step),
    )


# --- Composition: the readings panel -------------------------------------------


#: Plain heading for the readings panel. Flat on purpose: this is the one surface
#: where the plant is being measured rather than listened to, and a title in its
#: own voice here would blur the line the persona bible draws between the two.
INSTRUMENT_TITLE = "Readings"

#: The one line of prose on the readings panel, and it is about the panel rather
#: than about the plant — it exists to keep a reader from mistaking a block of
#: gauges for something the plant said.
INSTRUMENT_NOTE = (
    "Everything this plant's current state actually consists of. "
    "Instruments beside it, not its own words."
)

#: The events whose rows the readings panel is assembled from, in the order their
#: instruments appear. The fullest ordinary row leads, so the four readings that
#: apply to any living plant come first and in their usual order; each event after
#: it contributes only what the ones before it did not already have, because
#: :func:`_instrument_fields` keeps the first field of any given name.
#:
#: Deliberately not simply ``LifeEvent`` in declaration order: the events that
#: contribute nothing new (thirst, drought, steady, death, germination) would just
#: be passes, and the order below is the reading order of the finished panel.
_INSTRUMENT_EVENTS: tuple[LifeEvent, ...] = (
    LifeEvent.FLOURISHING,  # moisture, stage, age, crown
    LifeEvent.DIEBACK,      # + wood lost
    LifeEvent.BLOOM,        # + flowerings
    LifeEvent.EPIPHYTE,     # + the passenger's age
    LifeEvent.REBIRTH,      # + the line behind it
    LifeEvent.RINGS,        # + the finished years, and which of them scarred
)


def _instrument_applies(
    event: LifeEvent,
    plant: structure.Structure,
    state: voice.VoiceState,
    rings: tuple[structure.Ring, ...],
) -> bool:
    """Whether this event's row describes something the plant actually has.

    The four instruments every living plant carries need no guard — a healthy
    plant's ``Wood lost`` reading of ``0 of 300`` is a true and useful thing to
    say, and so is a crown of zero growing tips on a dead one. The four guarded
    below are different in kind: each of their rows is written for a plant that is
    *in* that event, and read against a plant that has never been there it would
    state something false rather than something dull. A plant that has never
    flowered has no first flowering, a first-generation plant has no line behind
    it, and a record with no finished years in it is not a record of zero good
    years.
    """
    if event is LifeEvent.BLOOM:
        return plant.stats.bloom_count > 0
    if event is LifeEvent.EPIPHYTE:
        return state.hosting or plant.epiphyte is not None
    if event is LifeEvent.REBIRTH:
        return plant.generation > 1
    if event is LifeEvent.RINGS:
        return bool(rings)
    return True


def _instrument_fields(
    plant: structure.Structure,
    state: voice.VoiceState,
    moisture_value: float,
    seconds_per_step: float,
    rings: tuple[structure.Ring, ...],
) -> tuple[Field, ...]:
    """Every instrument that applies to this plant right now, each one once.

    Assembled by walking :data:`_INSTRUMENT_EVENTS` and taking the union of the
    per-event rows :func:`_fields` already builds, keeping the first field of each
    name. That is the whole point of doing it this way rather than writing a
    second, flat list of readings: there is exactly one place that knows how to
    build a ``Wood lost`` or an ``Epiphyte`` reading, and it is the same place that
    knew before this panel existed, so the two can never drift apart.
    """
    seen: dict[str, Field] = {}
    for event in _INSTRUMENT_EVENTS:
        if not _instrument_applies(event, plant, state, rings):
            continue
        for field in _fields(event, plant, moisture_value, seconds_per_step, rings):
            seen.setdefault(field.name, field)
    return tuple(seen.values())


def compose_instruments(
    plant: structure.Structure,
    moisture_value: float,
    seconds_per_step: float,
    rings: tuple[structure.Ring, ...] = (),
) -> Panel:
    """Frame the same plant as a set of readings: everything, measured, at once.

    The counterpart to :func:`compose`, and the reason that one can afford to
    carry nothing. Same plant, same instant, same accent — this is one message
    with two faces rather than two messages, so the colour does not jump when
    somebody turns it over — but the picture steps back to a thumbnail and the
    instruments take the message.

    Everything here is plain, in the register the persona bible reserves for
    readouts: the plant does not narrate its own moisture, and a panel that exists
    to answer "what is this actually made of" would be worse, not better, for
    being poetic about it. The plant's words are one button away, which is where
    they belong.

    Takes exactly the arguments :func:`compose` does, and for the same reason:
    everything on this panel is derived from the plant, and nothing on it is
    chosen. Callers are expected to build both panels from a single reading of the
    state so that the numbers here describe the same instant as the picture beside
    them.
    """
    state = voice.read_state(plant, moisture_value)
    event = life_event(state, showing_rings=bool(rings))
    return Panel(
        event=event,
        accent=accent(event, plant.seed, plant.stats.bloom_intensity),
        title=INSTRUMENT_TITLE,
        body=INSTRUMENT_NOTE,
        fields=_instrument_fields(plant, state, moisture_value, seconds_per_step, rings),
        image=ImagePlacement.THUMBNAIL,
        footer=footer(state, plant, seconds_per_step),
    )
