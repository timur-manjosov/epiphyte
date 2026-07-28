"""Tests for how the plant is framed. No Pillow, no Discord, no persistence.

Four properties matter here, and they are what the "Präsentation" section of
``CLAUDE.md`` commits to: the frame is a deterministic function of the plant's
state (same state, same colour, same shape — across processes too), every life
event genuinely has a *different* shape rather than one template with swapped
values, no event falls through to a generic default, and none of this added a
command or a setting for anyone to configure.

``test_no_new_command_surface`` is the one test here that touches ``bot`` at all,
and only to count its commands — the point of this module is that the design
decisions are testable without Discord in the first place.
"""

import dataclasses
import subprocess
import sys

import bot
import presentation
import structure
import voice
from presentation import ImagePlacement, LifeEvent

#: The adapter's real tick interval, so the day counts these tests read are the
#: ones the bot actually shows.
TICK = bot.TICK_INTERVAL_SECONDS


def _plant(
    nodes: int = 1,
    *,
    seed: int = 12345,
    generation: int = 1,
    steps: int | None = None,
    dead: int = 0,
    lineage_blooms: int = 0,
    stats: structure.LifeStats | None = None,
    epiphyte: structure.Epiphyte | None = None,
) -> structure.Structure:
    """A structure with ``nodes`` nodes, the first ``dead`` of them dead wood.

    Fabricated rather than grown: every field the frame reads is set directly, so
    a 1200-node flowering tree costs a list comprehension instead of weeks of
    simulated ticks. Mirrors ``tests/test_voice.py``'s helper of the same name.
    """
    base = structure.germinate(seed, generation=generation, lineage_blooms=lineage_blooms)
    body = tuple(
        dataclasses.replace(
            base.nodes[0],
            id=index,
            parent_id=index - 1 if index else None,
            state=structure.NodeState.DEAD if index < dead else base.nodes[0].state,
        )
        for index in range(max(1, nodes))
    )
    return dataclasses.replace(
        base,
        nodes=body,
        step_count=nodes if steps is None else steps,
        active_tips=tuple(node.id for node in body if node.state is structure.NodeState.TIP),
        stats=stats if stats is not None else base.stats,
        epiphyte=epiphyte,
    )


def _bloomable_stats() -> structure.LifeStats:
    """Life statistics of a plant that has banked enough health to be in flower."""
    return structure.LifeStats(
        healthy_steps=structure.BLOOM_HEALTHY_STEPS,
        bloom_steps=structure.SEED_BLOOM_STEPS,
        bloom_count=3,
        in_bloom=True,
    )


def _epiphyte() -> structure.Epiphyte:
    """A small second organism riding a host limb, aged a few hundred steps."""
    return structure.Epiphyte(
        host_node_id=0, structure=_plant(60, seed=777, steps=240)
    )


#: One plant-and-moisture pair per life event, chosen so ``voice.read_state``
#: genuinely reads that event rather than the test asserting it into place.
def _cases() -> dict[LifeEvent, tuple[structure.Structure, float]]:
    """Return a representative ``(plant, moisture)`` for every life event."""
    return {
        LifeEvent.GERMINATION: (_plant(1), 0.0),
        LifeEvent.REBIRTH: (_plant(1, generation=3, lineage_blooms=1), 0.0),
        LifeEvent.DIEBACK: (_plant(300, dead=60, steps=900), 0.03),
        LifeEvent.DROUGHT: (_plant(300, steps=900), 0.12),
        LifeEvent.THIRST: (_plant(300, steps=900), 0.30),
        LifeEvent.STEADY: (_plant(300, steps=900), 0.50),
        LifeEvent.FLOURISHING: (_plant(300, steps=900), 0.90),
        LifeEvent.BLOOM: (_plant(1500, steps=4000, stats=_bloomable_stats()), 0.80),
        LifeEvent.EPIPHYTE: (
            _plant(3000, steps=5000, epiphyte=_epiphyte()),
            0.60,
        ),
        LifeEvent.DEATH: (_plant(300, dead=300, steps=900), 0.0),
    }


# --- Every event is reachable, and reads as itself -----------------------------


def test_every_life_event_is_reachable_from_a_real_state():
    """Each event's representative plant actually reads as that event.

    Guards the test suite itself: every claim below is only worth as much as the
    states it is asserted against, so those states are run through the same
    ``voice.read_state`` the living message uses rather than hand-built.
    """
    for event, (plant, moisture_value) in _cases().items():
        assert presentation.compose(plant, moisture_value, TICK).event is event


def test_every_life_event_has_an_accent():
    """No event may fall through to a default colour — there is no default."""
    for event in LifeEvent:
        assert presentation.accent(event, seed=12345) > 0


# --- Determinism ---------------------------------------------------------------


def test_the_same_state_always_frames_identically():
    """Composing the same plant twice yields exactly the same panel."""
    for plant, moisture_value in _cases().values():
        first = presentation.compose(plant, moisture_value, TICK)
        second = presentation.compose(plant, moisture_value, TICK)
        assert first == second


#: Seeds spanning every value the bloom-hue gene can take. That gene is the seed's
#: ninth 7-bit field (see ``structure._allele``), so shifting an index into place
#: walks the whole ramp — ordinary small integers all read a hue of zero and would
#: silently test one colour 128 times over.
_BLOOM_GENE_SEEDS = tuple(index << 56 for index in range(128))


def test_accent_is_a_pure_function_of_event_and_seed():
    """The colour never depends on anything but the event and the plant's identity."""
    for event in LifeEvent:
        assert presentation.accent(event, 42) == presentation.accent(event, 42)
    # The one per-plant accent: a flowering plant wears its own bloom colour.
    blooms = {presentation.accent(LifeEvent.BLOOM, seed) for seed in _BLOOM_GENE_SEEDS}
    assert len(blooms) > 1
    fixed = {presentation.accent(LifeEvent.STEADY, seed) for seed in _BLOOM_GENE_SEEDS}
    assert len(fixed) == 1


def test_sigil_survives_a_new_process():
    """A plant's footer mark is the same in a freshly started interpreter.

    The same mistake ``test_voice.py`` guards against applies here: selecting with
    the built-in ``hash()``, whose salt is randomised per process, would give every
    plant a new mark on every restart — which is no mark at all.
    """
    script = "import presentation; print(presentation.sigil(4242))"
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == presentation.sigil(4242)


def test_different_seeds_wear_different_sigils():
    """The mark is an individual's signature, not a constant decoration."""
    assert len({presentation.sigil(seed) for seed in range(60)}) > 1


# --- Distinct shapes, not one template ----------------------------------------


def _signature(panel: presentation.Panel) -> tuple:
    """The panel's *structure*, with every value stripped out.

    Field names, their widths and where the image sits — deliberately not the
    numbers in them, so two events that differ only in the values they plug into
    the same row collide here instead of passing.
    """
    return (
        tuple((field.name, field.inline) for field in panel.fields),
        panel.image,
    )


def test_every_life_event_has_its_own_field_structure():
    """No two events may share a field row — that is the whole bar for this phase.

    Compared by shape alone (see ``_signature``): an event that merely swapped the
    numbers inside another event's row would be caught here.
    """
    signatures = {
        event: _signature(presentation.compose(plant, moisture_value, TICK))
        for event, (plant, moisture_value) in _cases().items()
    }
    assert len(set(signatures.values())) == len(LifeEvent), (
        f"life events share a field structure: {signatures}"
    )


def test_every_life_event_has_its_own_accent():
    """Ten events, ten distinguishable colours — a shared accent hides a state.

    Checked for *every* bloom gene, not one sample plant: the flowering accent is
    the only one that varies, and a raw ramp endpoint would land exactly on
    another event's colour for the two genes that sit at the ends of it.
    """
    fixed = {presentation.accent(event, 0) for event in LifeEvent if event is not LifeEvent.BLOOM}
    assert len(fixed) == len(LifeEvent) - 1
    for seed in _BLOOM_GENE_SEEDS:
        assert presentation.accent(LifeEvent.BLOOM, seed) not in fixed


def test_beginnings_accompany_the_words_and_everything_else_leads_with_the_picture():
    """A seedling is a few pixels of thread; it does not get the full-width slot."""
    panels = {
        event: presentation.compose(plant, moisture_value, TICK)
        for event, (plant, moisture_value) in _cases().items()
    }
    for event in (LifeEvent.GERMINATION, LifeEvent.REBIRTH):
        assert panels[event].image is ImagePlacement.THUMBNAIL
    for event in set(LifeEvent) - {LifeEvent.GERMINATION, LifeEvent.REBIRTH}:
        assert panels[event].image is ImagePlacement.FULL


def test_death_is_the_only_full_image_with_nothing_beside_it():
    """At death the bare grey body is the message; the frame gets out of its way."""
    plant, moisture_value = _cases()[LifeEvent.DEATH]
    panel = presentation.compose(plant, moisture_value, TICK)
    assert panel.fields == ()
    assert panel.image is ImagePlacement.FULL


def test_the_panel_opens_and_closes_with_the_plant():
    """Instrument count tracks how much there is to measure, not a fixed layout."""
    counts = {
        event: len(presentation.compose(plant, moisture_value, TICK).fields)
        for event, (plant, moisture_value) in _cases().items()
    }
    assert counts[LifeEvent.GERMINATION] == 0
    assert counts[LifeEvent.DROUGHT] < counts[LifeEvent.THIRST]
    assert counts[LifeEvent.THIRST] < counts[LifeEvent.STEADY]
    assert counts[LifeEvent.STEADY] < counts[LifeEvent.FLOURISHING]


def test_dieback_reports_the_wood_it_cost_instead_of_a_second_weather_reading():
    """The one state that destroys body permanently says how much, by name."""
    plant, moisture_value = _cases()[LifeEvent.DIEBACK]
    panel = presentation.compose(plant, moisture_value, TICK)
    lost = next(field for field in panel.fields if field.name == "Wood lost")
    assert lost.value == "60 of 300"


def test_rebirth_is_the_only_event_that_names_its_line():
    """Lineage belongs to the moment a successor comes up, not to every heartbeat."""
    panels = {
        event: presentation.compose(plant, moisture_value, TICK)
        for event, (plant, moisture_value) in _cases().items()
    }
    named = {
        event
        for event, panel in panels.items()
        if any(field.name == "Its line" for field in panel.fields)
    }
    assert named == {LifeEvent.REBIRTH}
    line = next(f for f in panels[LifeEvent.REBIRTH].fields if f.name == "Its line")
    assert line.value == "2 before it · 1 flowered"


def test_a_milestone_the_event_is_about_spans_the_whole_width():
    """Bloom and epiphyte are lifted out of the text; nothing else ever is."""
    for event, name in ((LifeEvent.BLOOM, "In flower"), (LifeEvent.EPIPHYTE, "Habitat")):
        plant, moisture_value = _cases()[event]
        panel = presentation.compose(plant, moisture_value, TICK)
        promoted = next(field for field in panel.fields if field.name == name)
        assert promoted.inline is False
        assert promoted.value  # the plant's own words, not a restated number
        assert promoted.value not in panel.body

    for event, (plant, moisture_value) in _cases().items():
        panel = presentation.compose(plant, moisture_value, TICK)
        wide = [field for field in panel.fields if not field.inline]
        assert len(wide) == (1 if event in (LifeEvent.BLOOM, LifeEvent.EPIPHYTE) else 0)


def test_a_carried_milestone_the_event_is_not_about_stays_in_the_text():
    """A flowering plant that has also seeded says so in its words, not in a field.

    Only the milestone the event *is* about is promoted; the rest keep their place
    in the description, so the field row never turns into a milestone list.
    """
    plant, moisture_value = _cases()[LifeEvent.BLOOM]
    panel = presentation.compose(plant, moisture_value, TICK)
    state = voice.read_state(plant, moisture_value)
    assert state.seeded  # the case plant has flowered long enough to set seed
    assert len([f for f in panel.fields if not f.inline]) == 1
    assert panel.body.count("\n\n") == 1  # passage, then the remaining milestone


# --- The footer: the one constant --------------------------------------------


def test_every_event_carries_the_same_footer_shape():
    """Sigil, generation, age — present on every event without exception."""
    for plant, moisture_value in _cases().values():
        panel = presentation.compose(plant, moisture_value, TICK)
        assert panel.footer.startswith(presentation.sigil(plant.seed))
        assert "generation" in panel.footer
        assert "day" in panel.footer


def test_the_footer_speaks_of_a_dead_plant_in_the_past_tense():
    """Death turns the age readout into the length of the life that was had."""
    plant, moisture_value = _cases()[LifeEvent.DEATH]
    assert "lived" in presentation.compose(plant, moisture_value, TICK).footer


def test_the_footer_carries_the_permanent_marks():
    """Seed and epiphyte are permanent, so they live in the constant line."""
    plant, moisture_value = _cases()[LifeEvent.EPIPHYTE]
    hosting = presentation.compose(plant, moisture_value, TICK).footer
    assert "hosting an epiphyte" in hosting

    ordinary, ordinary_moisture = _cases()[LifeEvent.STEADY]
    plain = presentation.compose(ordinary, ordinary_moisture, TICK).footer
    assert "hosting" not in plain and "seeded" not in plain


def test_age_is_reported_in_days_not_growth_steps():
    """A step is a constant real duration, so it is shown as one a reader owns."""
    plant, moisture_value = _cases()[LifeEvent.STEADY]  # 900 steps at one per hour
    panel = presentation.compose(plant, moisture_value, TICK)
    assert "37 days" in panel.footer
    assert next(f for f in panel.fields if f.name == "Age").value == "37 days"


# --- Tick stability ------------------------------------------------------------


def test_an_ordinary_heartbeat_does_not_reshape_the_frame():
    """Growth within a chapter, at an unchanged band, keeps colour and shape.

    The same rule the voice already follows: the living message is rebuilt every
    heartbeat, and rebuilding must not read as the frame changing its mind.
    """
    before = presentation.compose(_plant(300, steps=900), 0.50, TICK)
    after = presentation.compose(_plant(330, steps=901), 0.55, TICK)
    assert after.event is before.event
    assert after.accent == before.accent
    assert _signature(after) == _signature(before)


def test_crossing_into_dieback_reshapes_the_frame():
    """A transition that genuinely matters does change colour and shape."""
    withered = presentation.compose(_plant(300, steps=900), 0.12, TICK)
    parched = presentation.compose(_plant(300, dead=10, steps=900), 0.03, TICK)
    assert parched.accent != withered.accent
    assert _signature(parched) != _signature(withered)


# --- No new surface ------------------------------------------------------------


def test_no_new_command_surface():
    """This phase framed the message; it must not have added anything to command.

    Surface minimalism applies to the presentation layer exactly as it does to the
    plant: the frame is derived from state, never chosen, so there is no preview
    command, no style flag and no settings menu to find here.
    """
    assert {command.name for command in bot.client.tree.get_commands()} == {
        "plant",
        "epiphyte-channel",
        "help",
    }


def test_composition_takes_no_configuration():
    """``compose`` reads the plant and the tick interval, and nothing else.

    A style, theme or palette parameter would be a configuration surface wearing a
    function signature, so the signature itself is what this pins down.
    """
    import inspect

    parameters = list(inspect.signature(presentation.compose).parameters)
    assert parameters == ["plant", "moisture_value", "seconds_per_step"]
