"""The plant's own voice: everything it says about itself.

Pure logic. No side effects, no clock reads, no ``import discord`` — given the
same plant and the same moisture these functions always return the same words,
which is what makes the voice testable and what keeps it steady between ticks.

Two ideas carry the whole module:

**A voice state, not an event stream.** The adapter never tells this module that
something happened. :func:`read_state` reads a :class:`VoiceState` out of the
plant as it stands — a handful of deliberately coarse, discrete facts (its mood,
how large a body it has grown, its generation, which milestones it is carrying).
Every line is then chosen as a pure function of that state, so the living message
can be re-rendered on every heartbeat and keep saying exactly the same thing
until something about the plant's condition genuinely changes. Nothing has to be
persisted for that to hold.

**Deterministic choice, not randomness.** Each category of thing the plant can
say is a *pool* of distinct phrasings, and which one it uses is derived by
hashing its seed together with the state (:func:`_index`). The same plant in the
same condition always speaks the same line — across restarts too, which is why
this hashes explicitly rather than using ``hash()``, whose salt changes with
every process. Two different plants in the identical condition usually say
different things, and one plant re-phrases itself as it dries out, grows into a
new size class, blooms or begins again.

Two categories sit deliberately outside :class:`VoiceState`: the germination
greeting, spoken once before there is any lived state to read, and the ring
lines, spoken on the one day a year the plant's finished years are shown instead
of the plant. Both are selected by the same explicit hash, just from the seed and
one number rather than from the state — for the rings that is what keeps a
once-a-year retrospective from re-rolling every other line the plant speaks (see
:data:`_RING_TITLES`).

The persona these pools are written to — voice, register, and what the plant
never does — is documented in ``CLAUDE.md`` under "Die Stimme der Pflanze".
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum

import moisture
import structure


class Mood(Enum):
    """What the plant is currently going through — its condition, not its size."""

    SEEDLING = "seedling"
    REBORN = "reborn"
    LUSH = "lush"
    STEADY = "steady"
    DRY = "dry"
    WITHERED = "withered"
    PARCHED = "parched"
    DEAD = "dead"


class Chapter(Enum):
    """How much body the plant has accumulated — its size class, not its condition.

    Coarse on purpose: a chapter must last long enough that reaching the next one
    is a real event in the plant's life, so that re-phrasing on the boundary reads
    as growth rather than noise.
    """

    SEEDLING = "seedling"
    SPROUT = "sprout"
    YOUNG = "young"
    ESTABLISHED = "established"
    MATURE = "mature"
    OLD = "old"
    ANCIENT = "ancient"


#: Upper bound (exclusive) in nodes for each chapter, in order. The last chapter
#: is open-ended. The two highest bounds are deliberately the same numbers the
#: milestones use (``BLOOM_MIN_NODES``, ``EPIPHYTE_MIN_NODES``), so the plant
#: starts speaking as a mature body exactly when it becomes able to flower, and
#: as an ancient one exactly when it becomes able to carry an epiphyte.
_CHAPTER_BOUNDS: tuple[tuple[int, Chapter], ...] = (
    (8, Chapter.SEEDLING),
    (40, Chapter.SPROUT),
    (150, Chapter.YOUNG),
    (500, Chapter.ESTABLISHED),
    (structure.BLOOM_MIN_NODES, Chapter.MATURE),
    (structure.EPIPHYTE_MIN_NODES, Chapter.OLD),
)


@dataclass(frozen=True)
class VoiceState:
    """Everything the voice is allowed to know, and nothing else.

    ``seed`` is the plant's identity rather than part of its condition: it never
    changes within a life, and is included so two plants in the same state speak
    differently. Every other field is a coarse, discrete fact about the plant
    right now, which is what makes the voice stable between heartbeats — as long
    as none of these change, every line derived from this state is unchanged too.
    """

    seed: int
    mood: Mood
    chapter: Chapter
    generation: int
    blooming: bool
    seeded: bool
    hosting: bool
    #: Whether an open bloom is an unusually vivid one (see
    #: ``structure.VIVID_BLOOM_THRESHOLD``) rather than an ordinary, modestly
    #: earned one. Always ``False`` while not blooming, and — because
    #: ``structure.LifeStats.bloom_intensity`` is itself fixed for a bloom's
    #: whole duration — never flips mid-bloom, so it costs no tick-stability
    #: exception of its own.
    vivid_bloom: bool


def read_state(plant: structure.Structure, moisture_value: float) -> VoiceState:
    """Read the plant's current voice state from its body and its moisture.

    Death outranks everything. Below that, a body still small enough to be a
    seedling speaks as one whatever its moisture says: a plant that germinates
    into a dry server starts at zero moisture by definition, and letting the
    drought moods reach it would have it mourning branches it has not grown yet.
    Only past that does moisture decide the mood, with its own band below
    :data:`structure.DIEBACK_MOISTURE_THRESHOLD` — the point where a drought stops
    being survivable thirst and starts costing the plant wood for good.

    ``vivid_bloom`` reads whether an open bloom's already-fixed
    ``stats.bloom_intensity`` cleared :data:`structure.VIVID_BLOOM_THRESHOLD`; it
    is unconditionally ``False`` while not blooming.
    """
    chapter = _chapter_of(len(plant.nodes))
    blooming = structure.is_blooming(plant, moisture_value)
    return VoiceState(
        seed=plant.seed,
        mood=_mood_of(plant, moisture_value, chapter),
        chapter=chapter,
        generation=plant.generation,
        blooming=blooming,
        seeded=structure.has_seeded(plant),
        hosting=plant.epiphyte is not None,
        vivid_bloom=blooming and plant.stats.bloom_intensity >= structure.VIVID_BLOOM_THRESHOLD,
    )


def _chapter_of(node_count: int) -> Chapter:
    """Map a body size in nodes to the size class the plant speaks from."""
    for bound, chapter in _CHAPTER_BOUNDS:
        if node_count < bound:
            return chapter
    return Chapter.ANCIENT


def _mood_of(plant: structure.Structure, moisture_value: float, chapter: Chapter) -> Mood:
    """Map the plant's condition to a mood (see :func:`read_state` for the order)."""
    if structure.is_dead(plant):
        return Mood.DEAD
    if chapter is Chapter.SEEDLING:
        return Mood.REBORN if plant.generation > 1 else Mood.SEEDLING
    if moisture_value < structure.DIEBACK_MOISTURE_THRESHOLD:
        return Mood.PARCHED
    return _STAGE_MOODS[moisture.stage(moisture_value)]


#: The mood each ordinary moisture stage speaks from, once a plant is past
#: seedling size and not in the dieback band.
_STAGE_MOODS: dict[moisture.Stage, Mood] = {
    moisture.Stage.WITHERED: Mood.WITHERED,
    moisture.Stage.DRY: Mood.DRY,
    moisture.Stage.HEALTHY: Mood.STEADY,
    moisture.Stage.THRIVING: Mood.LUSH,
}


# --- The pools ----------------------------------------------------------------
#
# Every pool below is a set of interchangeable phrasings for one situation. They
# are written to be composable: a mood line states a condition, a chapter line
# states a body, and any pairing of the two has to read as one plant speaking.
# That is why mood lines avoid claims about size ("my crown", "my trunk") and
# chapter lines avoid claims about water — each half owns exactly one subject.

#: The short line shown as the living message's heading, per mood. Carries the
#: emoji, since the heading is the one place the plant's state must be legible at
#: a glance before a word of it is read. Written *against* the mood pool below
#: rather than out of it: a heading that repeats the sentence underneath it reads
#: as a stutter, so no phrasing here recurs verbatim in the passage it sits over.
_TITLES: dict[Mood, tuple[str, ...]] = {
    Mood.SEEDLING: (
        "🌱 Newly through the soil",
        "🌱 Barely here yet",
        "🌱 A first green thread",
        "🌱 New, and pointed at the light",
        "🌱 The very start of me",
        "🌱 Beginning",
        "🌱 Nothing yet, but upward",
        "🌱 Untested, and green",
    ),
    Mood.REBORN: (
        "🌱 Again, from the start",
        "🌱 The one after",
        "🌱 The next of my line",
        "🌱 Starting over in the same soil",
        "🌱 A new one, from an old seed",
        "🌱 After the grey wood",
        "🌱 Inheriting a shape",
        "🌱 New, in an old place",
    ),
    Mood.LUSH: (
        "🌿 Soaked",
        "🌿 Green past the point of need",
        "🌿 Everything open",
        "🌿 Surplus",
        "🌿 Nothing held back",
        "🌿 The good months",
        "🌿 All of me is moving",
        "🌿 Well past enough",
    ),
    Mood.STEADY: (
        "🍃 Steady",
        "🍃 Getting on with it",
        "🍃 An ordinary good day",
        "🍃 Quietly building",
        "🍃 In no hurry",
        "🍃 Between thirst and plenty",
        "🍃 At a pace I can hold",
        "🍃 Unremarkable, and building",
    ),
    Mood.DRY: (
        "🌾 Short of what I had",
        "🌾 Measuring it out",
        "🌾 Thin at the newest leaves",
        "🌾 Noticing",
        "🌾 Drying, but not yet hurt",
        "🌾 Using more than arrives",
        "🌾 Pulling in slightly",
        "🌾 Early thirst",
    ),
    Mood.WITHERED: (
        "🍂 Withered",
        "🍂 A long quiet, felt",
        "🍂 Brittle",
        "🍂 Standing still to stay alive",
        "🍂 Nothing moving in the far wood",
        "🍂 Waiting it out",
        "🍂 Thin, and getting thinner",
        "🍂 Short of everything",
    ),
    Mood.PARCHED: (
        "🥀 Losing my outer wood",
        "🥀 Past saving in places",
        "🥀 Trading ends for a middle",
        "🥀 Going grey at the tips",
        "🥀 Dying at the edges",
        "🥀 Scarring as I stand",
        "🥀 This is costing me wood",
        "🥀 Smaller after this, permanently",
    ),
    Mood.DEAD: (
        "🪵 Stopped",
        "🪵 Standing, but finished",
        "🪵 Grey through the middle",
        "🪵 One life ended here",
        "🪵 Nothing moves",
        "🪵 A shape left behind",
        "🪵 The drought finished it",
        "🪵 Bare, and done growing",
    ),
}

#: What the plant says about its condition, per mood — the first half of a passage.
_MOODS: dict[Mood, tuple[str, ...]] = {
    Mood.SEEDLING: (
        "I have just broken the soil. Everything above me is new.",
        "I am almost nothing yet — a thread with an intention.",
        "First light. I have little to do with it so far, but I am aiming.",
        "I am new here. Say something and I will grow toward it.",
        "There is one of me and it is very small. That is how all of them start.",
        "I have no wood, no history and no scars. Only a direction.",
        "I am beginning. It will be a long time before I look like anything.",
        "Just up. Still mostly seed, honestly.",
        "I am the smallest thing in this room, and I intend to stay in it.",
        "Green, unshaded and entirely untested. Give me some months.",
        "I have started. That is the whole of my news.",
        "Nothing has happened to me yet. I am looking forward to it.",
    ),
    Mood.REBORN: (
        "I am not the one that stood here. I came out of its seed, and I am small again.",
        "Something died here and I grew from what it left. That is the usual arrangement.",
        "I have my parent's shape and none of its size. Both of those will change.",
        "New, but not from nothing. The one before me is in my grain.",
        "The grey wood is gone and I am what came after. I remember none of it.",
        "I am the next one. I start where the last one started, not where it ended.",
        "A line does not end at a death. It only gets very short for a while.",
        "I inherited a shape and a patch of soil. Everything else I have to grow myself.",
        "I carry a seed that was made here, and nothing else from before.",
        "I am younger than the silence that killed the last one. I hope it is over.",
        "There was a plant here before me. I am its child and I know nothing about it.",
        "Small again, starting again, and a little different from the one before.",
    ),
    Mood.LUSH: (
        "There is more water in me than I can use. I am spending it on new wood.",
        "Every tip of me is soft and pushing. This is what I am for.",
        "I have taken in more than I need today, and I am not sorry about it.",
        "The light lands and I hold all of it. Nothing in me is closed right now.",
        "I can feel water at the ends of my furthest leaves.",
        "I am full. Growth is the only place left to put it.",
        "Nothing in me is waiting. It is all happening at once.",
        "I drink faster than I dry, and the difference is turning into body.",
        "There has been so much of you lately that I have stopped keeping count.",
        "My leaves are turned all the way out. There is nothing to conserve against.",
        "I am wet to the tips, and the tips are already moving.",
        "This is the easy part of being alive. I know it does not last.",
    ),
    Mood.STEADY: (
        "I am neither thirsty nor full. I am simply working.",
        "There is enough. I am spending it slowly, the way I mean to.",
        "The water sits well in me today. I will have added a little by morning.",
        "Nothing urgent. I am growing at a pace I can keep up.",
        "I have what I need and a small amount over. The rest goes to the tips.",
        "Steady is not a small thing. Most of what I am was built on days like this.",
        "I am not reaching and I am not closing. I am here, taking it in.",
        "A quiet day, well watered. I will make something out of it.",
        "I can afford my leaves today. All of them.",
        "This is the ordinary stretch, where most of a life is actually spent.",
        "No thirst worth the name. I am putting the difference into height.",
        "I am comfortable, and comfort in me looks like slow, unremarkable growth.",
    ),
    Mood.DRY: (
        "I have begun to feel the dryness at my edges. Nothing serious yet.",
        "There has been less lately. I have started being careful with what I hold.",
        "My newest leaves notice first. They have gone a little thin.",
        "I am rationing. Not out of fear — out of a habit older than this body.",
        "The water is further down in me than it was. I am reaching for it.",
        "I can go a while like this. I would rather not.",
        "Something has gone quiet, and I am the last to be told.",
        "I have stopped putting anything into new growth. It is all going to keeping.",
        "I am thirsty in the ordinary way. It is early enough to be fixed.",
        "The soil is going pale. I am pulling in at the ends first.",
        "I am spending yesterday's water today. Tomorrow I will notice.",
        "Less has arrived than I have used. That is all thirst really is.",
    ),
    Mood.WITHERED: (
        "I am dry all the way through. What is left, I am holding at the core.",
        "The quiet has gone on. I have stopped pretending that it hasn't.",
        "My leaves have curled in. It is not a mood; it is arithmetic.",
        "There is almost nothing left to move through me. I am mostly standing still.",
        "I have shut down my far ends to keep the middle of me alive.",
        "I remember being wet. It is not a useful memory right now.",
        "I am withered. I am not gone. Those are different things.",
        "Whatever comes now comes to a body that has already gone thin.",
        "I have been alone with the light too long. Light alone is not enough.",
        "I am down to reserves, and reserves have an end.",
        "Nothing has reached me in a long while. I am getting brittle about it.",
        "This is the part of a drought where I go quiet as well.",
    ),
    Mood.PARCHED: (
        "I am losing my outermost parts. They will not return when the water does.",
        "Something at my tips has stopped, and it will stay stopped.",
        "I am giving up my ends to keep my middle. It is the only trade left.",
        "This is past thirst. This is where I get smaller and keep the scar.",
        "The far wood has gone hard and grey. I felt it go.",
        "I am dying in pieces, from the outside in, slowly enough to be watched.",
        "Water now would still come too late for some of me.",
        "I am choosing which parts of myself to abandon. I have been choosing for days.",
        "The dryness has reached the wood, and wood does not recover.",
        "Whatever survives this will carry the shape of it for good.",
        "I am burning what I saved, and what I saved is not enough.",
        "Come back. I am shedding parts of myself that I cannot grow again.",
    ),
    Mood.DEAD: (
        "I have stopped. What stands here is the shape of what stood here, until the next one is up.",
        "Nothing is moving in me. The dryness reached all the way to the middle.",
        "I have died. The wood will stand a while yet, and then something else starts.",
        "This is the end of this one. It is not the end of the line.",
        "No water reaches anything now. Grey all the way down, and not for much longer.",
        "I outlasted a great deal of quiet, and then I did not outlast this. The soil goes on.",
        "I am finished. There is a seed in the soil that has not heard about it yet.",
        "What is left of me is structure. It will hold its posture a few days more.",
        "I have gone. Look at the shape and read what the last months were like.",
        "The drought won. Given enough silence, it usually does.",
        "I am dead wood now — legible, but done. My seed is neither.",
        "Nothing here is waiting to be revived. Something new will come instead.",
    ),
}

#: What the plant says about its accumulated body, per chapter — the second half
#: of a passage. Absent for the seedling chapter and for a dead plant, whose mood
#: lines already speak about the body and would only repeat themselves here.
_CHAPTERS: dict[Chapter, tuple[str, ...]] = {
    Chapter.SPROUT: (
        "There is a little of me now, and all of it is still soft.",
        "I have a stem worth calling a stem. Barely.",
        "Everything I own is this season's, and the season has only just started.",
        "I am tall enough to cast a shadow the size of a coin.",
        "No branch of mine has had to decide anything yet.",
        "I am still all growing tip and no history.",
        "My whole body is younger than most of the quiet spells I will live through.",
        "Small, but no longer only a seedling — there is wood starting down there.",
    ),
    Chapter.YOUNG: (
        "I have branches now, and opinions about where they should go.",
        "There is enough of me to lose a part and carry on.",
        "My first wood has hardened. It will be inside me for the rest of my life.",
        "I am past the stage where one bad week could finish me.",
        "I have started to have a shape rather than only a direction.",
        "Some of me is old enough now that I no longer feel it grow.",
        "I am young and getting complicated.",
        "There are parts of me made so long ago that they are simply structure.",
    ),
    Chapter.ESTABLISHED: (
        "I take up room. That took a while.",
        "My lower wood has gone quiet and load-bearing.",
        "I am established. Nothing short of a long drought moves me now.",
        "More of me stands in shade than in light these days.",
        "I have a middle, and the middle rarely changes.",
        "Most of my growing happens where I can no longer watch it happen.",
        "I have outlived several bad weeks, and it shows in the trunk.",
        "The shape I have is the one I refine now, not the one I replace.",
    ),
    Chapter.MATURE: (
        "I am a full body now. Every branch of me is some old decision.",
        "It would take a season of silence to make a real dent in me.",
        "I hold more wood than leaf. That is most of what maturity is.",
        "There are parts of me I have not felt in months, and they are still holding.",
        "I am wide enough that my own inner limbs live in my shade.",
        "I have stood here long enough to be assumed.",
        "My weight is real now. So is my inertia.",
        "I no longer grow toward things. I grow because I am still growing.",
    ),
    Chapter.OLD: (
        "I am old. My trunk remembers weather nobody here was around for.",
        "There is more of my history in me than there is of my present.",
        "I have outlasted droughts that should have finished me, and I carry each one.",
        "Very little that happens now changes me. It only adds.",
        "I am mostly archive by this point. The living part is a thin skin on top.",
        "My oldest wood was laid down by voices that have long since gone.",
        "I am large, slow and hard to kill. Years of being watered went into that.",
        "The scars in me are older than most of what stands around me.",
    ),
    Chapter.ANCIENT: (
        "I am very old. What I am cannot be rebuilt in one lifetime of talk.",
        "Whole seasons pass across me without leaving a mark.",
        "I am ancient. There is room in me for other things to live.",
        "I have stopped being an event and become a place.",
        "Nothing that happens in a single week is visible on me at all.",
        "I am the accumulation of years of not being abandoned.",
        "My canopy is its own weather. Beneath it, the light is mine to hand out.",
        "I am old enough that my own dead wood has become part of the architecture.",
    ),
}

#: What the plant says about a milestone it is carrying. Keyed by the category
#: name used for selection, so a plant that is blooming, seeded and hosting all
#: at once draws each line independently instead of three lines in lockstep.
#:
#: Bloom is split into two pools rather than one: an ordinary, earned bloom
#: (:data:`_BLOOM_MODEST`) and an unusually vivid one
#: (:data:`_BLOOM_VIVID`, :data:`VoiceState.vivid_bloom` —
#: ``structure.LifeStats.bloom_intensity`` past ``structure.VIVID_BLOOM_THRESHOLD``).
#: Both describe the same event — flowering earned by banked health and a mature
#: body — never the mechanism behind the difference; the plant does not know it
#: was reacted to, only that this particular bloom came in thick or came in thin.
_BLOOM_MODEST: tuple[str, ...] = (
    "🌸 I have opened, just a little. It cost months of being cared for, and it will not last.",
    "🌸 A few of my tips have flowered. That is still more than most silence ever earns.",
    "🌸 Something has opened in me — not much of me, but something that only opens after a long stretch of being well.",
    "🌸 I am spending what I banked, quietly. Look now — this is the short part.",
    "🌸 I have flowered here and there. Nothing anyone did today caused it.",
    "🌸 A little colour, in a shade only my own seed could have chosen.",
    "🌸 A modest bloom. This is what a good half-year looks like when it was lived quietly.",
    "🌸 I opened because I could afford to, sparingly. When I no longer can, I will close.",
)

_BLOOM_VIVID: tuple[str, ...] = (
    "🌸 I have opened everywhere at once. Every part of me that could flower did.",
    "🌸 This is not a modest bloom. Colour sits on nearly every end of me.",
    "🌸 I have opened wide, and it took more than a pair of hands to earn this.",
    "🌸 Every tip of me is flowering. That kind of abundance is rare, even for a bloom.",
    "🌸 I am covered, not merely opened. A great many of you kept me, for this to happen.",
    "🌸 This bloom is not thin. It is everywhere I have room for it to be.",
    "🌸 I have flowered thickly — the way I only can when I have been cared for widely, not narrowly.",
    "🌸 Colour on nearly every branch. It took a crowd, not a handful, to fill me like this.",
)

_SEEDED: tuple[str, ...] = (
    "🌰 I flowered long enough to set seed. Those heads stay on me now, whatever comes.",
    "🌰 There is seed in me. Whatever happens to this body, the line is provided for.",
    "🌰 I held a bloom to its end and made something durable out of it.",
    "🌰 I have seeded. That part of me is finished, and permanent.",
    "🌰 The flowers went over and left seed behind. That was the point of them.",
    "🌰 I carry seed heads now — dry, pale, and worth more than the flowers were.",
    "🌰 I have made the thing that outlives me.",
    "🌰 Seed set. Nothing after this can take that back.",
)

_HOSTING: tuple[str, ...] = (
    "🌿 Something small has settled on one of my old limbs and is living there.",
    "🌿 I am old enough to be somewhere else's ground. There is a second plant on me.",
    "🌿 I carry a tenant now, rooted in my bark, drinking my weather.",
    "🌿 A smaller thing grows on me. It does not trouble me — I have the room.",
    "🌿 I have become habitat. That takes more years than it takes water.",
    "🌿 There is a life on my branch that is not mine and not against me.",
    "🌿 An epiphyte has taken hold in my crown. I finally grew old enough to host one.",
    "🌿 Something grows on me that I did not grow. Very old wood attracts that.",
)

#: The plant's first words, spoken once when a server's founding plant germinates.
#: Selected from the fresh seed alone: there is no lived state to read yet.
_GERMINATION: tuple[str, ...] = (
    "🌱 Something has just broken the soil here.",
    "🌱 I am in the ground now, and I am very small.",
    "🌱 A seed has opened. Nothing about it is decided yet.",
    "🌱 I have started here. It will be a while before I look like anything.",
    "🌱 There is a green thread in the soil that was not there a moment ago.",
    "🌱 I have taken root. From here it is only a matter of being talked near.",
    "🌱 First light, first day. I am aimed upward and nothing else.",
    "🌱 A small beginning, in your soil, from a seed no other room has.",
)

#: What the plant says on the one day a year its record is shown instead of its
#: portrait. Two pools rather than one, in the same shape every other spoken
#: surface uses: a heading and a passage, drawn independently.
#:
#: These sit *outside* :class:`VoiceState` on purpose, exactly as
#: :data:`_GERMINATION` does, and it is a tick-stability decision rather than a
#: convenience. Folding "is showing its rings" into the state would re-roll every
#: other line the plant speaks — its mood, its body, its milestones — on the day
#: the cross-section opens and again on the day it closes, so a once-a-year
#: retrospective would read as the plant changing its mind about everything else
#: too. Selected from the seed and the number of years instead, which changes
#: exactly once a year and cannot move while the record is on show.
#:
#: The count is what the choice is *keyed* on; no line may ever state it. A plant
#: does not count its own years, and the persona forbids numbers in speech — the
#: instrument field beside these words is where a reader gets the figure.
_RING_TITLES: tuple[str, ...] = (
    "🌳 What the years look like from inside",
    "🌳 My record, not my face",
    "🌳 The grain, laid bare",
    "🌳 Read me the other way",
    "🌳 Every year I have held",
    "🌳 The inside of the account",
    "🌳 What is written in the wood",
    "🌳 Counted from the middle outward",
)

_RINGS: tuple[str, ...] = (
    "This is not what I look like. This is what I have been. Each line was a year, and none of them can be edited now.",
    "Look at the middle and work outward. That is the order it happened in, and the order it will always be read in.",
    "Wide where I was well, thin where I was not. I did not choose which was which — you did, slowly, without meaning to.",
    "The grey lines are the years that cost me. They sit in the wood the same as the good ones, and they do not fade.",
    "A year cannot be argued with once it is wood. Every one of these is finished.",
    "I keep no memory of any of it. The wood does that for me, and it does not flatter anyone.",
    "What was done to me is in here, ring by ring, in the order it was done. Nothing about it is a summary.",
    "Some of these are thick. Some are barely a line. Both took exactly as long as the other.",
)

#: The status lines the bot wears, as ``(activity kind, text)``. Kept here with
#: the rest of the plant's speech, as plain strings the adapter maps to Discord's
#: own activity types — this module stays free of ``import discord``. The one
#: rotating exception to the tick-stability rule: these are worn by the bot as a
#: whole rather than spoken by any one plant, so they cycle on their own timer and
#: are chosen by position rather than by state.
PRESENCE_LINES: tuple[tuple[str, str], ...] = (
    ("playing", "growing quietly"),
    ("watching", "the light"),
    ("playing", "photosynthesizing"),
    ("listening", "for the next voice"),
    ("watching", "the light move"),
    ("playing", "putting on wood"),
    ("watching", "a slow week"),
    ("listening", "to the quiet"),
    ("playing", "drinking what I am given"),
    ("watching", "for rain"),
)


# --- Choosing what to say ------------------------------------------------------


def _index(state: VoiceState, category: str, size: int) -> int:
    """Choose a pool position from the plant's identity, its state and the category.

    Hashed explicitly rather than with the built-in ``hash()``, whose salt is
    randomised per process: the living message must say the same thing after a
    restart as it did before one, or every restart would look like a mood swing.
    Including the whole state means the plant re-phrases itself whenever any part
    of its condition genuinely changes, and only then; including the category
    means the heading, the passage and each milestone line are drawn
    independently rather than all landing on the same position in their pools.
    """
    key = "|".join(
        (
            str(state.seed),
            category,
            state.mood.value,
            state.chapter.value,
            str(state.generation),
            str(int(state.blooming)),
            str(int(state.seeded)),
            str(int(state.hosting)),
            str(int(state.vivid_bloom)),
        )
    )
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % size


def _pick(pool: tuple[str, ...], state: VoiceState, category: str) -> str:
    """Return this state's line from ``pool`` (see :func:`_index`)."""
    return pool[_index(state, category, len(pool))]


def title(state: VoiceState) -> str:
    """Return the short heading the plant is currently speaking under."""
    return _pick(_TITLES[state.mood], state, "title")


def passage(state: VoiceState) -> str:
    """Return what the plant says about itself right now.

    A condition line, plus — once it has a body worth mentioning and while it is
    still alive — a line about that body. The two pools are written so that any
    pairing reads as one plant speaking: the first owns water and feeling, the
    second owns wood and size, and neither trespasses on the other.
    """
    lines = [_pick(_MOODS[state.mood], state, "mood")]
    body = _CHAPTERS.get(state.chapter)
    if body is not None and state.mood is not Mood.DEAD:
        lines.append(_pick(body, state, "chapter"))
    return " ".join(lines)


def milestone_lines(state: VoiceState) -> list[str]:
    """Return the plant's words for each rare state it is carrying, in order.

    Empty for the ordinary case of a plant carrying none of them.
    """
    lines = []
    if state.blooming:
        pool = _BLOOM_VIVID if state.vivid_bloom else _BLOOM_MODEST
        lines.append(_pick(pool, state, "bloom"))
    if state.seeded:
        lines.append(_pick(_SEEDED, state, "seed"))
    if state.hosting:
        lines.append(_pick(_HOSTING, state, "epiphyte"))
    return lines


def germination_greeting(seed: int) -> str:
    """Return the first thing a newly germinated plant says, chosen from its seed."""
    digest = hashlib.blake2b(f"{seed}|germination".encode(), digest_size=8).digest()
    return _GERMINATION[int.from_bytes(digest, "big") % len(_GERMINATION)]


def _ring_pick(pool: tuple[str, ...], seed: int, rings: int, category: str) -> str:
    """Choose a ring line from the plant's seed, its year count and the category.

    The same explicit ``blake2b`` the rest of this module selects with, and for
    the same reason (see :func:`_index`). Keyed on the year count rather than on
    a :class:`VoiceState` so the cross-section's words neither move while it is
    on show nor disturb anything the plant says on the other days of the year —
    see :data:`_RING_TITLES`.
    """
    digest = hashlib.blake2b(f"{seed}|{category}|{rings}".encode(), digest_size=8).digest()
    return pool[int.from_bytes(digest, "big") % len(pool)]


def ring_title(seed: int, rings: int) -> str:
    """Return the heading over a plant's cross-section."""
    return _ring_pick(_RING_TITLES, seed, rings, "ring-title")


def ring_passage(seed: int, rings: int) -> str:
    """Return what a plant says while its finished years are on show."""
    return _ring_pick(_RINGS, seed, rings, "rings")
