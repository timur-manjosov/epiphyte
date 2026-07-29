"""Tests for how the plant is framed. No Pillow, no Discord, no persistence.

The properties that matter here are what the "Präsentation" section of
``CLAUDE.md`` commits to: the frame is a deterministic function of the plant's
state (same state, same colour, same words — across processes too), no event falls
through to a generic default, every event's instrument row is still its own rather
than one template with swapped values, and none of this added a command or a
setting for anyone to configure.

Since the ambient/readings split, one more property joins them and gets the most
attention below: **the living channel message carries no instruments at all.**
That message is seen by everyone in a server whether they asked for it or not, and
the whole point of the split is that it shows the plant and nothing else. The
per-event rows still exist — they were relocated, not deleted — and the tests for
them now read them where they now live: through ``_fields`` directly, and through
the readings panel assembled out of it.

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


#: A record of finished years, for the one event that is not a condition of the
#: plant but a reading of what it has lived through. Kept apart from ``_cases()``
#: because it genuinely is apart: every other event is resolved from the plant
#: alone, while this one needs a second input the adapter supplies once a year.
_RINGS: tuple[structure.Ring, ...] = (
    structure.Ring(year=2026, vitality=0.62, scarred=False),
    structure.Ring(year=2027, vitality=0.09, scarred=True),
    structure.Ring(year=2028, vitality=0.71, scarred=False),
)


def _panels() -> dict[LifeEvent, presentation.Panel]:
    """One composed panel per life event, including the cross-section.

    The ring event outranks everything but the identity changes, so its plant is
    an ordinary steady one — a panel that had to be forced into the ring event by
    a contrived plant would not be testing the resolution order.
    """
    panels = {
        event: presentation.compose(plant, moisture_value, TICK)
        for event, (plant, moisture_value) in _cases().items()
    }
    steady, steady_moisture = _cases()[LifeEvent.STEADY]
    panels[LifeEvent.RINGS] = presentation.compose(steady, steady_moisture, TICK, _RINGS)
    return panels


# --- Every event is reachable, and reads as itself -----------------------------


def test_every_life_event_is_reachable_from_a_real_state():
    """Each event's representative plant actually reads as that event.

    Guards the test suite itself: every claim below is only worth as much as the
    states it is asserted against, so those states are run through the same
    ``voice.read_state`` the living message uses rather than hand-built.
    """
    for event, panel in _panels().items():
        assert panel.event is event


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


def _row(event: LifeEvent) -> tuple[presentation.Field, ...]:
    """The instrument row ``presentation`` builds for one event, on its own plant.

    Reaches into ``_fields`` deliberately. Since the split these rows no longer
    reach the living message, but they are not gone: they are the readings panel's
    single source of truth, and the design property they carry — one event, one
    shape — is still worth pinning down at the place that decides it.

    The cross-section has no entry in ``_cases()`` — it is resolved from a record
    rather than from a condition, so it borrows the ordinary steady plant, exactly
    as ``_panels()`` does.
    """
    rings = _RINGS if event is LifeEvent.RINGS else ()
    plant, moisture_value = _cases()[LifeEvent.STEADY if rings else event]
    return presentation._fields(event, plant, moisture_value, TICK, rings)


def _names(fields: tuple[presentation.Field, ...]) -> tuple[str, ...]:
    """The row's shape with every value stripped out — names only.

    Deliberately not the numbers, so two events that differ only in what they plug
    into the same row collide here instead of passing.
    """
    return tuple(field.name for field in fields)


def test_every_event_with_instruments_has_its_own_row():
    """No two events may share an instrument row, values aside.

    The two exceptions are the two ends of a life: germination and death both have
    an empty row, because at both there is nothing to measure that the plant has
    not already said better itself. Everything between them is distinct.
    """
    rows = {event: _names(_row(event)) for event in LifeEvent}
    assert rows[LifeEvent.GERMINATION] == ()
    assert rows[LifeEvent.DEATH] == ()

    populated = {event: row for event, row in rows.items() if row}
    assert len(set(populated.values())) == len(populated), (
        f"life events share an instrument row: {populated}"
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


def test_bloom_accent_pales_toward_snow_as_intensity_falls():
    """A modest bloom (low ``bloom_intensity``, see Phase 15) wears the same hue
    as a vivid one, only washed paler — reusing the existing ramp and lift, not a
    second colour axis for vividness."""
    for seed in (0, 1 << 56, 42, 12345):
        vivid = presentation.accent(LifeEvent.BLOOM, seed, intensity=1.0)
        modest = presentation.accent(LifeEvent.BLOOM, seed, intensity=structure.BLOOM_INTENSITY_FLOOR)
        assert vivid != modest

        def distance_from_snow(color: int) -> int:
            return sum(
                abs(((color >> shift) & 0xFF) - ((presentation.SNOW >> shift) & 0xFF))
                for shift in (16, 8, 0)
            )

        assert distance_from_snow(modest) < distance_from_snow(vivid), f"seed {seed}"


def test_bloom_accent_stays_distinct_from_fixed_accents_at_every_intensity():
    """The floor's paler colour must not accidentally land on another event's
    fixed accent either — checked across every bloom gene, at both extremes."""
    fixed = {presentation.accent(event, 0) for event in LifeEvent if event is not LifeEvent.BLOOM}
    for seed in _BLOOM_GENE_SEEDS:
        for intensity in (0.0, structure.BLOOM_INTENSITY_FLOOR, 1.0):
            assert presentation.accent(LifeEvent.BLOOM, seed, intensity) not in fixed


def test_the_instrument_row_opens_and_closes_with_the_plant():
    """Instrument count tracks how much there is to measure, not a fixed layout."""
    counts = {event: len(_row(event)) for event in LifeEvent}
    assert counts[LifeEvent.GERMINATION] == 0
    assert counts[LifeEvent.DROUGHT] < counts[LifeEvent.THIRST]
    assert counts[LifeEvent.THIRST] < counts[LifeEvent.STEADY]
    assert counts[LifeEvent.STEADY] < counts[LifeEvent.FLOURISHING]


def test_dieback_reports_the_wood_it_cost_instead_of_a_second_weather_reading():
    """The one state that destroys body permanently says how much, by name."""
    lost = next(field for field in _row(LifeEvent.DIEBACK) if field.name == "Wood lost")
    assert lost.value == "60 of 300"


def test_rebirth_is_the_only_event_that_names_its_line():
    """Lineage belongs to the moment a successor comes up, not to every heartbeat."""
    named = {event for event in LifeEvent if any(f.name == "Its line" for f in _row(event))}
    assert named == {LifeEvent.REBIRTH}
    line = next(f for f in _row(LifeEvent.REBIRTH) if f.name == "Its line")
    assert line.value == "2 before it · 1 flowered"


# --- The ambient panel: the plant, and nothing beside it ----------------------


def test_the_living_message_carries_no_instruments_on_any_event():
    """The one property this whole split exists for, asserted over every event.

    The cross-section is the single, argued-for exception (see ``compose``): a
    record nobody can date is not a record, and the plant is forbidden from
    counting its own years out loud.
    """
    for event, panel in _panels().items():
        if event is LifeEvent.RINGS:
            continue
        assert panel.fields == (), f"{event} still shows instruments on the living message"


def test_the_cross_section_keeps_its_row_including_the_moisture_rider():
    """Phase 19's exception survives the stripping, in full and in its own order.

    Two readings of the record, then the present weather last — the ordering is
    the part that matters: it is what stops the once-a-year retrospective from
    hiding a drought that is running on the day it happens to fall.
    """
    panel = _panels()[LifeEvent.RINGS]
    assert _names(panel.fields) == ("Rings", "Scar rings", "Moisture")
    assert panel.fields[0].value == "3 years"
    assert panel.fields[1].value == "2027"


def test_the_living_message_always_leads_with_the_full_size_picture():
    """Every event, without exception — including the two that used to be thumbnails.

    A germinating or newly reborn plant being a few pixels of thread in a lot of
    soil is *true*, and the panel that exists to show the plant should show it.
    """
    for event, panel in _panels().items():
        assert panel.image is ImagePlacement.FULL, f"{event} does not lead with the picture"


def test_a_germinating_and_a_reborn_plant_are_full_size_and_wordless_of_instruments():
    """The two events the old frame treated as exceptions, checked directly."""
    for event in (LifeEvent.GERMINATION, LifeEvent.REBIRTH):
        plant, moisture_value = _cases()[event]
        panel = presentation.compose(plant, moisture_value, TICK)
        assert panel.event is event
        assert panel.image is ImagePlacement.FULL
        assert panel.fields == ()
        assert panel.title and panel.body  # still the plant's own words


def test_every_milestone_the_plant_carries_stays_in_its_own_words():
    """Nothing is lifted out of the text into a field anymore — there is no field.

    A flowering plant that has also seeded says both in the body, in the plant's
    own words, rather than having one of them restated as a promoted row.
    """
    plant, moisture_value = _cases()[LifeEvent.BLOOM]
    panel = presentation.compose(plant, moisture_value, TICK)
    state = voice.read_state(plant, moisture_value)
    assert state.blooming and state.seeded
    for line in voice.milestone_lines(state):
        assert line in panel.body
    assert panel.fields == ()


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
    assert "37 days" in presentation.compose(plant, moisture_value, TICK).footer
    readings = presentation.compose_instruments(plant, moisture_value, TICK)
    assert next(f for f in readings.fields if f.name == "Age").value == "37 days"


# --- Tick stability ------------------------------------------------------------


def test_an_ordinary_heartbeat_does_not_reshape_the_frame():
    """Growth within a chapter, at an unchanged band, keeps colour and words.

    The same rule the voice already follows: the living message is rebuilt every
    heartbeat, and rebuilding must not read as the frame changing its mind. With
    the instruments gone the frame has *less* that can move between heartbeats,
    not more — the moisture percentage was the one thing on it that used to.
    """
    before = presentation.compose(_plant(300, steps=900), 0.50, TICK)
    after = presentation.compose(_plant(330, steps=901), 0.55, TICK)
    assert after.event is before.event
    assert after.accent == before.accent
    assert (after.title, after.body, after.image) == (before.title, before.body, before.image)


def test_crossing_into_dieback_reshapes_the_frame():
    """A transition that genuinely matters does change colour and words."""
    withered = presentation.compose(_plant(300, steps=900), 0.12, TICK)
    parched = presentation.compose(_plant(300, dead=10, steps=900), 0.03, TICK)
    assert parched.event is not withered.event
    assert parched.accent != withered.accent
    assert (parched.title, parched.body) != (withered.title, withered.body)


def test_a_percentage_no_longer_moves_under_the_picture_between_heartbeats():
    """Two heartbeats an hour apart, at different moisture, are the same panel.

    The strongest form of the tick-stability rule, and one the frame could not
    make before: a moisture field re-rendered every hour meant the living message
    visibly changed on heartbeats where nothing about the plant had.
    """
    plant = _plant(300, steps=900)
    assert presentation.compose(plant, 0.50, TICK) == presentation.compose(plant, 0.55, TICK)


# --- The readings panel: everything, measured, behind a button ----------------


def test_the_readings_panel_carries_every_instrument_the_plant_has():
    """The union of every applicable event's row, and nothing missing from it."""
    plant, moisture_value = _cases()[LifeEvent.FLOURISHING]
    readings = presentation.compose_instruments(plant, moisture_value, TICK)
    assert _names(readings.fields) == ("Moisture", "Stage", "Age", "Crown", "Wood lost")


def test_the_readings_panel_never_repeats_an_instrument():
    """Several events' rows share a moisture reading; it must appear exactly once."""
    for plant, moisture_value in _cases().values():
        for rings in ((), _RINGS):
            names = _names(presentation.compose_instruments(plant, moisture_value, TICK, rings).fields)
            assert len(names) == len(set(names)), names


def test_the_readings_panel_reads_the_current_state_not_a_generic_one():
    """Values come from the plant that was passed, at the moisture that was passed."""
    plant, _ = _cases()[LifeEvent.DIEBACK]
    dry = presentation.compose_instruments(plant, 0.03, TICK)
    assert next(f for f in dry.fields if f.name == "Moisture").value == "3%"
    assert next(f for f in dry.fields if f.name == "Wood lost").value == "60 of 300"

    wet = presentation.compose_instruments(plant, 0.91, TICK)
    assert next(f for f in wet.fields if f.name == "Moisture").value == "91%"
    assert next(f for f in wet.fields if f.name == "Stage").value == "Thriving"


def test_the_readings_panel_leaves_out_what_the_plant_has_never_had():
    """A guarded row would state something false, not merely something dull.

    A plant that has never flowered has no first flowering, a founder has no line
    behind it, an unencumbered plant has no passenger, and an empty record is not
    a record of zero good years.
    """
    plant, moisture_value = _cases()[LifeEvent.STEADY]
    names = _names(presentation.compose_instruments(plant, moisture_value, TICK).fields)
    for absent in ("Flowerings", "Its line", "Epiphyte", "Rings", "Scar rings"):
        assert absent not in names, f"{absent} must not be claimed for a plant without one"


def test_the_readings_panel_includes_what_the_plant_does_have():
    """Each guarded row appears exactly when the plant genuinely has that thing."""
    flowering, flowering_moisture = _cases()[LifeEvent.BLOOM]
    assert "Flowerings" in _names(
        presentation.compose_instruments(flowering, flowering_moisture, TICK).fields
    )

    successor, successor_moisture = _cases()[LifeEvent.REBIRTH]
    assert "Its line" in _names(
        presentation.compose_instruments(successor, successor_moisture, TICK).fields
    )

    host, host_moisture = _cases()[LifeEvent.EPIPHYTE]
    assert "Epiphyte" in _names(
        presentation.compose_instruments(host, host_moisture, TICK).fields
    )

    steady, steady_moisture = _cases()[LifeEvent.STEADY]
    with_record = _names(
        presentation.compose_instruments(steady, steady_moisture, TICK, _RINGS).fields
    )
    assert "Rings" in with_record and "Scar rings" in with_record


def test_a_zero_reading_is_still_reported_where_it_is_true():
    """The unguarded instruments say zero rather than disappearing.

    ``Wood lost: 0 of 300`` on a healthy plant is a true and useful thing to
    read; the guards exist for rows that would state something false, not for
    rows that would state something unremarkable.
    """
    plant, moisture_value = _cases()[LifeEvent.STEADY]
    readings = presentation.compose_instruments(plant, moisture_value, TICK)
    assert next(f for f in readings.fields if f.name == "Wood lost").value == "0 of 300"


def test_the_readings_panel_is_the_same_message_turned_over():
    """Same accent, same footer, same event — one message with two faces.

    A colour that jumped on the toggle would read as a second, different message
    rather than as the other side of the one being looked at.
    """
    for plant, moisture_value in _cases().values():
        ambient = presentation.compose(plant, moisture_value, TICK)
        readings = presentation.compose_instruments(plant, moisture_value, TICK)
        assert readings.event is ambient.event
        assert readings.accent == ambient.accent
        assert readings.footer == ambient.footer


def test_the_readings_panel_steps_the_picture_back_and_stays_plain():
    """The numbers lead, and none of them is dressed up as the plant speaking."""
    plant, moisture_value = _cases()[LifeEvent.STEADY]
    readings = presentation.compose_instruments(plant, moisture_value, TICK)
    ambient = presentation.compose(plant, moisture_value, TICK)
    assert readings.image is ImagePlacement.THUMBNAIL
    assert readings.title == presentation.INSTRUMENT_TITLE
    assert readings.body == presentation.INSTRUMENT_NOTE
    assert readings.title != ambient.title and readings.body != ambient.body


def test_the_readings_panel_is_deterministic():
    """Same plant, same instant, same readings — like everything else here."""
    for plant, moisture_value in _cases().values():
        first = presentation.compose_instruments(plant, moisture_value, TICK)
        second = presentation.compose_instruments(plant, moisture_value, TICK)
        assert first == second


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
    """``compose`` reads the plant, the tick interval and its record — nothing else.

    A style, theme or palette parameter would be a configuration surface wearing a
    function signature, so the signature itself is what this pins down. ``rings``
    is not one: it carries derived state (the plant's own finished years, from
    ``structure.rings``) rather than a preference, nobody can set it, and the two
    values it can take are decided by the calendar rather than by anyone's taste.
    The distinction this test exists to hold is *derived versus chosen*, not
    argument count — an accepted parameter here has to be a fact about the plant.
    """
    import inspect

    expected = ["plant", "moisture_value", "seconds_per_step", "rings"]
    assert list(inspect.signature(presentation.compose).parameters) == expected
    # The readings panel is a second *view* of the same facts, never a second set
    # of options: it takes exactly what the ambient panel takes, and nothing more.
    assert list(inspect.signature(presentation.compose_instruments).parameters) == expected


def test_the_cross_section_is_the_only_thing_rings_can_change():
    """Passing rings may only ever flip the panel into the ring event; it can
    never quietly restyle an ordinary day. Checked by composing every other
    event's plant twice, with and without a record on file."""
    for event, (plant, moisture_value) in _cases().items():
        with_rings = presentation.compose(plant, moisture_value, TICK, _RINGS)
        without = presentation.compose(plant, moisture_value, TICK)
        if event in (LifeEvent.DEATH, LifeEvent.GERMINATION, LifeEvent.REBIRTH):
            assert with_rings == without, f"{event} must outrank the cross-section"
        else:
            assert with_rings.event is LifeEvent.RINGS, f"{event} should yield to it"
            assert without.event is event
