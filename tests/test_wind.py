"""The wind: a passing gust while somebody is typing (Phase 20).

The smallest addition in the project, and the one with the most to prove about
what it is *not*. It is not a vitality signal, and — unlike the tree rings, the
only other non-signal here — it is not a record either: it accumulates nothing,
is persisted nowhere, and is forgotten by every part of the system the moment it
passes. The first section states that structurally, the way Phase 17 and Phase
19 stated their equivalents: by signature, so a future change that quietly wires
the weather into the body fails here rather than being noticed years later.

The second section is the timing — the linger window has to outlast Discord's
own ten-second typing refresh so a gust cannot flicker between keystrokes, and
fall far short of the hour between heartbeats so it can never become the plant's
normal face — and the third is the deliberate absence of any scaling with how
many people are typing: the wind carries no information, because information is
what a signal is made of.

The last section is the only one that draws, in the narrowly-scoped exception
``CLAUDE.md`` permits. It holds the two claims that are properties of the image
itself: that still air is byte-identical to the pre-Phase-20 renderer rather
than merely calibrated to resemble it, and that both wind states are fully
deterministic, so the project's seeded-determinism guarantee survives an
argument whose *value* is momentary.
"""

import inspect

from PIL import Image

# render/Pillow are imported for the final section only — see the module
# docstring for why those two claims cannot be stated in pure logic.
import bot
import moisture
import render
import storage
import structure
from structure import (
    WIND_LINGER_SECONDS,
    genome_from_seed,
    germinate,
    grow,
    wind_is_stirring,
)

#: A healthy plant with a substantial crown, for the drawing section.
SEED = 4242
TENDED = 0.85


def _body(steps: int = 700):
    """A grown body and its genome, the same pair every drawing test uses."""
    genome = genome_from_seed(SEED)
    return grow(germinate(SEED), genome, TENDED, steps, breadth=0.7, rhythm=0.5), genome


# --- Neither a signal nor a record ---------------------------------------------
#
# Phase 17 proved voice activity cannot reach the body because grow() has nowhere
# to put it; Phase 19 proved the same for the rings. The wind needs both of those
# claims and one more that neither of them did: it must not reach *storage*
# either, since the rings at least keep a record and this keeps nothing.


def test_the_wind_has_nowhere_to_reach_growth_or_vitality_from():
    """``grow`` takes no wind argument and ``wind_is_stirring`` takes nothing but
    an elapsed time — no body, no moisture, no seed, no guild. There is no term
    the weather could feed back into the plant through, which is what makes this
    an appearance rather than a sixth signal."""
    assert set(inspect.signature(grow).parameters) == {
        "structure", "genome", "moisture", "steps",
        "breadth", "rhythm", "reaction_warmth", "thread_depth",
    }
    assert set(inspect.signature(wind_is_stirring).parameters) == {"seconds_since_typing"}
    # The moisture model is likewise untouched: no function of it takes, returns
    # or is named for anything the weather could arrive through.
    assert "wind_is_stirring" not in dir(moisture)
    for name in ("decay", "water", "next_watering", "effective_water_amount"):
        parameters = inspect.signature(getattr(moisture, name)).parameters
        assert "wind" not in parameters and "typing" not in parameters


def test_nothing_about_the_wind_is_ever_persisted():
    """The state a gust leaves behind, stated as the absence of anywhere to leave
    it: no column of the stored guild state, no field of the structure that is
    serialized, and no storage function mentions it. A restart forgets the
    weather, which is the correct lifetime for weather."""
    assert not [field for field in storage.GuildState.__dataclass_fields__ if "wind" in field]
    assert not [name for name in dir(storage.Storage) if "wind" in name.lower()]

    body, _ = _body(steps=40)
    assert not [key for key in structure.serialize(body) if "wind" in key]
    # And the round trip is indifferent to it: a body that was drawn windswept
    # deserializes to exactly the body that was drawn still.
    assert structure.serialize(structure.deserialize(structure.serialize(body))) == \
        structure.serialize(body)


def test_the_only_thing_the_bot_keeps_is_one_timestamp_per_guild():
    """Bounded by construction: the highest-frequency event in the bot writes a
    single float into a single dict entry, so somebody typing all afternoon costs
    exactly what somebody typing once costs. There is nothing here to prune,
    because there is nothing here that grows."""
    client = bot.EpiphyteClient.__new__(bot.EpiphyteClient)
    client._typing = {}
    client._typing[7] = 1000.0
    for moment in range(1001, 1400):  # a keystroke-refresh storm
        client._typing[7] = float(moment)
    assert client._typing == {7: 1399.0}


# --- How long a gust lasts ------------------------------------------------------


def test_the_air_is_still_before_anybody_has_typed():
    """No typing on record — a fresh start, or a guild nobody has written in
    since — is still air, never a gust by default."""
    assert wind_is_stirring(None) is False


def test_a_gust_outlasts_discords_own_typing_refresh_by_a_wide_margin():
    """Discord re-sends a typing indicator roughly every ten seconds while
    somebody keeps typing. The window has to be several times that or the crown
    would drop and lift between one keystroke's refresh and the next — flicker,
    not weather."""
    assert WIND_LINGER_SECONDS >= 6 * 10
    assert wind_is_stirring(10.0) is True
    assert wind_is_stirring(30.0) is True


def test_a_gust_is_far_shorter_than_the_heartbeat_that_draws_it():
    """The other bound: the living message is redrawn once an hour, so a window
    well under that can never become the plant's ordinary face. It is a gust
    caught in a picture that was going to be drawn anyway."""
    assert WIND_LINGER_SECONDS < bot.TICK_INTERVAL_SECONDS / 10


def test_the_air_stills_again_once_typing_stops():
    """Both sides of the edge, and the fact that it is an edge at all: the wind
    ends by itself, from elapsed time alone, with nothing to switch it off."""
    assert wind_is_stirring(WIND_LINGER_SECONDS) is True
    assert wind_is_stirring(WIND_LINGER_SECONDS + 0.001) is False
    assert wind_is_stirring(3600.0) is False


def test_an_event_stamped_a_hair_ahead_of_the_clock_still_counts():
    """A negative elapsed time means somebody just typed, not that something is
    wrong. It reads as a gust rather than being rejected."""
    assert wind_is_stirring(-2.0) is True


# --- No scaling with how many people are typing ---------------------------------


def test_the_wind_is_a_state_rather_than_an_amount():
    """The load-bearing decision of the phase, and it is enforced by the type
    rather than by calibration: the answer is a bool, so there is no dial a
    headcount could be written onto. Two people typing stir exactly as much air
    as one, because the moment the wind measured *anything* it would be a signal
    in ambience's clothing."""
    assert isinstance(wind_is_stirring(1.0), bool)
    assert wind_is_stirring(1.0) is wind_is_stirring(WIND_LINGER_SECONDS)


def test_more_typists_change_nothing_end_to_end():
    """The same claim through the bot's own path: however many people type, the
    guild keeps one timestamp and the renderer is asked for the same picture."""
    client = bot.EpiphyteClient.__new__(bot.EpiphyteClient)
    client._typing = {}
    now = 1_000_000.0
    client._typing[3] = now  # one person
    alone = client._wind(3, now + 5.0)
    for _ in range(20):  # a whole room of them, in the same second
        client._typing[3] = now
    assert client._wind(3, now + 5.0) is alone is True

    body, genome = _body(steps=200)
    assert render.render(body, TENDED, genome, 0.0, True).getvalue() == \
        render.render(body, TENDED, genome, 0.0, True).getvalue()


def test_a_guild_nobody_has_typed_in_reads_as_still():
    """The bot's read of a guild with no entry at all, which is every guild until
    somebody types and every guild again after a restart."""
    client = bot.EpiphyteClient.__new__(bot.EpiphyteClient)
    client._typing = {}
    assert client._wind(99, 1_000_000.0) is False


# --- Properties of the drawing itself -------------------------------------------
#
# The narrowly-scoped exception CLAUDE.md permits: these two claims are about
# pixels and cannot be stated in pure logic. Everything above stays pure.


def _pixels(wind: bool, steps: int = 700):
    """Render the standard body with and without wind, as an RGB image."""
    body, genome = _body(steps)
    return Image.open(render.render(body, TENDED, genome, 0.0, wind)).convert("RGB")


def test_still_air_is_byte_identical_to_the_renderer_before_this_existed():
    """The isolation, in bytes rather than in intent: the wind is an argument
    that defaults to off, and off is not calibrated to look like the old
    behaviour — it *is* the old behaviour, since a zero lean is added to every
    coordinate exactly. Every existing baseline in this suite therefore keeps
    comparing against the picture it always compared against."""
    body, genome = _body(steps=400)
    plain = render.render(body, TENDED, genome).getvalue()
    assert render.render(body, TENDED, genome, 0.0).getvalue() == plain
    assert render.render(body, TENDED, genome, 0.0, False).getvalue() == plain
    assert render.render(body, TENDED, genome, 0.0, True).getvalue() != plain


def test_both_wind_states_are_fully_deterministic():
    """The tension this phase had to resolve, resolved: a momentary Discord event
    does not put randomness into the renderer. Wind is a second *deterministic*
    picture, chosen between exactly the way the cross-section is chosen between,
    so "the same arguments always draw the same bytes" still holds — all that is
    momentary is which arguments the caller passes."""
    body, genome = _body(steps=300)
    gust = render.render(body, TENDED, genome, 0.0, True).getvalue()
    assert render.render(body, TENDED, genome, 0.0, True).getvalue() == gust
    assert render.render(body, TENDED, genome, 0.0, False).getvalue() == \
        render.render(body, TENDED, genome, 0.0, False).getvalue()


def test_a_plant_always_takes_the_gust_the_same_way():
    """Which way an individual leans comes from its own seed, like its leaf
    placement, its blossom rotations and its cross-section's silhouette — so a
    plant is recognisable in the wind, and two plants are not blown identically."""
    other = genome_from_seed(SEED + 1)
    body, genome = _body(steps=300)
    twin = grow(germinate(SEED + 1), other, TENDED, 300, breadth=0.7, rhythm=0.5)
    assert render.render(body, TENDED, genome, 0.0, True).getvalue() != \
        render.render(twin, TENDED, other, 0.0, True).getvalue()
    leans = {
        seed % 2 == 0 for seed in (SEED, SEED + 1)
    }
    assert leans == {True, False}  # the two test plants lean opposite ways


def test_the_lean_is_a_few_pixels_at_the_top_and_nothing_at_the_foot():
    """"Subtle" as a number. The measure Phase 17 used for the root system —
    share of the frame that changes — is the wrong instrument for a coherent
    shift of an object that is already there, so the bound is the displacement
    itself: at most a few pixels at the highest tip, falling away quadratically
    so the trunk is untouched. Compared against the drought sag, which is the
    posture change that means trouble, it is a small fraction."""
    top_lean = render._WIND_MAX_SWAY / render.SUPERSAMPLE
    assert 2.0 <= top_lean <= 6.0
    assert top_lean < render._DROOP_MAX / render.SUPERSAMPLE / 10.0
    # Quadratic falloff: half way up the plant the lean is a quarter of that —
    # a single pixel, which is why the body reads as leaning rather than bending.
    assert top_lean * 0.5 ** render._WIND_FALLOFF <= 1.0

    still, blown = _pixels(False), _pixels(True)
    changed = [
        (x, y)
        for y in range(still.height)
        for x in range(still.width)
        if still.getpixel((x, y)) != blown.getpixel((x, y))
    ]
    assert changed, "a gust that changes nothing is not a gust"
    # Nothing moves at the foot of the plant or in the soil: the earth line sits
    # at render.HEIGHT - 90, and the lean is zero at the base by construction.
    assert max(y for _, y in changed) < render.HEIGHT - 90


def test_a_sprout_is_left_out_of_the_weather():
    """Twenty-two pixels of stem have nothing to sway, so a just-germinated plant
    renders identically in a gust — the same abstention the root system makes for
    a body with no trunk to flare."""
    sprout = germinate(SEED)
    genome = genome_from_seed(SEED)
    assert render.render(sprout, TENDED, genome, 0.0, True).getvalue() == \
        render.render(sprout, TENDED, genome).getvalue()


def test_the_cross_section_is_out_of_reach_of_the_wind():
    """Wind moves a standing plant; a cross-section is not one. ``render_rings``
    has no wind argument to pass and no caller that could pass one, so the one
    day a year the record is shown, it is shown in still air by construction."""
    assert set(inspect.signature(render.render_rings).parameters) == {"rings", "seed"}
