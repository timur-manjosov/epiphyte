"""How the plant is framed: the shape and the colour of the message around it.

Pure logic. No side effects, no clock reads, no ``import discord`` and no Pillow —
this module decides *what the container looks like* and hands back a plain
:class:`Panel`, which the adapter pours into a ``discord.Embed``. That split is
the same one :mod:`voice` already makes: the interesting decision is testable
without Discord, and ``bot.py`` keeps only the four lines that know what an embed
is.

Three ideas carry the module, and they mirror the ones the plant itself is built
on:

**The frame is derived, never configured.** Accent colour, field structure and
image placement are all read out of the plant's current state — the same state
:mod:`voice` reads. There is no theme, no setting and no command that changes any
of it, exactly as there is none that changes the plant's own appearance. What the
frame looks like is one more honest readout, not a preference.

**One life event, one shape.** :func:`life_event` collapses the plant's condition
into a single :class:`LifeEvent`, and every event gets its *own* field structure —
not one template with different values dropped in. A germinating plant is a small
thumbnail and a sentence; a dead one is a full-width image and nothing else; a
plant in drought shows one instrument where a thriving one shows four. The
ordering in :func:`life_event` is the whole design decision: endings and
beginnings outrank what is happening to the body, which outranks what the body has
become, which outranks the ordinary day.

**A quiet constant underneath.** The footer is the one element whose shape never
changes: a seed-derived sigil, the generation, the age in days, and whichever
permanent marks the plant carries. It is the only place lineage and age appear on
most events, which is what lets the field rows differ so freely above it.

The boundary this module must not cross: it frames the rendered image, it never
touches it. Everything inside the PNG — the body, the palette, the foliage,
the blossoms — belongs to :mod:`render` alone. See "Präsentation" in ``CLAUDE.md``.
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

    Purely a slot in the message — the PNG itself is identical either way. It is
    the strongest lever the frame has for making a major life event feel unlike an
    ordinary day, and it costs nothing but a different attachment reference.
    """

    #: Full width, below the text: the picture leads.
    FULL = "full"
    #: Small, top right: the words lead and the plant accompanies them.
    THUMBNAIL = "thumbnail"


@dataclass(frozen=True)
class Field:
    """One plain readout beside the plant — an instrument, never part of its speech.

    ``inline`` false makes the field span the message's whole width, which is
    reserved for a milestone the plant has actually earned (see
    :func:`_promoted_milestone`).
    """

    name: str
    value: str
    inline: bool = True


@dataclass(frozen=True)
class Panel:
    """Everything the adapter needs to build the message, and nothing Discord-shaped.

    ``title`` and ``body`` are the plant's own words, taken from :mod:`voice`
    unchanged — this module decides where they sit, never what they say.
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


def life_event(state: voice.VoiceState) -> LifeEvent:
    """Collapse the plant's condition into the one event that shapes its frame.

    The order below *is* the design, and it reads in four tiers:

    1. **An ending or a beginning** — death, a founding germination, a successor's
       rebirth. The body's identity has changed, which outranks anything happening
       to it.
    2. **What is happening to it** — dieback, a flowering, drought, thirst. All
       four are time-limited and moving, including the bloom: it drains the very
       reserve that opened it and ends on its own, so it belongs with the changing
       states rather than with the standing ones.
    3. **What it has become** — carrying an epiphyte. Permanent, and therefore
       ranked *below* the passing states: a tree that has become habitat still
       shows its thirst when it is thirsty.
    4. **The ordinary day** — flourishing, or simply steady.
    """
    if state.mood is voice.Mood.DEAD:
        return LifeEvent.DEATH
    if state.mood is voice.Mood.SEEDLING:
        return LifeEvent.GERMINATION
    if state.mood is voice.Mood.REBORN:
        return LifeEvent.REBIRTH
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
# with substituted values — the field *names*, their count, and whether the image
# leads or accompanies all change with what the plant is going through.


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


def _fields(
    event: LifeEvent,
    plant: structure.Structure,
    moisture_value: float,
    seconds_per_step: float,
) -> tuple[Field, ...]:
    """Return the instrument row for one event — its own, not a shared template.

    Read as a set, the rows say something the individual rows cannot: the panel
    opens up as the plant does and closes down as it suffers. A flourishing plant
    carries four instruments, an ordinary one three, a thirsty one two, a plant in
    drought a single number, and a germinating or dead one none at all — at those
    two ends there is nothing to measure that the plant has not already said
    better itself.
    """
    if event is LifeEvent.GERMINATION:
        return ()
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


def _image_placement(event: LifeEvent) -> ImagePlacement:
    """Whether the picture leads this event, or accompanies its words.

    A germinating or newly reborn plant is a thread a few pixels tall: rendered
    full width it is mostly empty soil, so it accompanies the sentence instead of
    dominating it. Everything else leads with the picture — death most of all,
    where the bare grey body *is* the message and the frame gets out of its way.
    """
    if event in (LifeEvent.GERMINATION, LifeEvent.REBIRTH):
        return ImagePlacement.THUMBNAIL
    return ImagePlacement.FULL


# --- Composition ---------------------------------------------------------------


#: Field name a promoted milestone line is shown under, per event that promotes one.
_PROMOTED_NAMES: dict[LifeEvent, str] = {
    LifeEvent.BLOOM: "In flower",
    LifeEvent.EPIPHYTE: "Habitat",
}

#: Which milestone the event is *about*, keyed by the order
#: :func:`voice.milestone_lines` returns them in.
_PROMOTED_KIND: dict[LifeEvent, str] = {
    LifeEvent.BLOOM: "bloom",
    LifeEvent.EPIPHYTE: "host",
}


def _milestones(state: voice.VoiceState) -> dict[str, str]:
    """Label :func:`voice.milestone_lines`'s output by which milestone each line is.

    That function returns the carried milestones in a fixed order — bloom, then
    seed, then epiphyte — so zipping it against the same order recovers which line
    is which without reaching into :mod:`voice`'s pools.
    """
    carried = [
        kind
        for kind, held in (("bloom", state.blooming), ("seed", state.seeded), ("host", state.hosting))
        if held
    ]
    return dict(zip(carried, voice.milestone_lines(state)))


def _promoted_milestone(event: LifeEvent, state: voice.VoiceState) -> tuple[Field | None, list[str]]:
    """Lift the milestone this event is about out of the text, into a full-width field.

    A bloom or an epiphyte is the rarest thing the plant will ever have to report,
    and burying it as the third paragraph of a description reads as an afterthought.
    Promoted, it spans the message's whole width — the only field that ever does —
    while any other milestone the plant happens to be carrying stays in the text.
    Returns ``(field or None, the lines that remain in the body)``.
    """
    lines = _milestones(state)
    kind = _PROMOTED_KIND.get(event)
    promoted = lines.pop(kind, None) if kind is not None else None
    remaining = list(lines.values())
    if promoted is None:
        return None, remaining
    return Field(_PROMOTED_NAMES[event], promoted, inline=False), remaining


def compose(
    plant: structure.Structure, moisture_value: float, seconds_per_step: float
) -> Panel:
    """Frame a plant: its event, its colour, its words and the shape they sit in.

    The words themselves come from :mod:`voice` untouched — this module never
    writes what the plant says, only where it lands. ``seconds_per_step`` is the
    adapter's tick interval, passed in rather than read from a clock or a config so
    the whole composition stays a pure function of the plant.
    """
    state = voice.read_state(plant, moisture_value)
    event = life_event(state)
    promoted, remaining = _promoted_milestone(event, state)

    body = [voice.passage(state)]
    if remaining:
        body.append("\n".join(remaining))

    fields = _fields(event, plant, moisture_value, seconds_per_step)
    if promoted is not None:
        fields = (promoted, *fields)

    return Panel(
        event=event,
        accent=accent(event, plant.seed, plant.stats.bloom_intensity),
        title=voice.title(state),
        body="\n\n".join(body),
        fields=fields,
        image=_image_placement(event),
        footer=footer(state, plant, seconds_per_step),
    )
