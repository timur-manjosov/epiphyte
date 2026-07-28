"""Tests for the plant's voice. No Pillow, no Discord, no persistence.

Three properties matter here, and they are the ones the persona bible in
``CLAUDE.md`` commits to: the same plant in the same condition always says the
same thing (determinism, across processes as well as within one), an ordinary
heartbeat that changes nothing meaningful leaves the words alone (tick
stability), and every situation the plant can be in actually has words for it
(no silent gaps in the pools).
"""

import dataclasses
import re
import subprocess
import sys

import moisture
import structure
import voice
from voice import Chapter, Mood, VoiceState


def _plant(nodes: int = 1, *, seed: int = 12345, generation: int = 1) -> structure.Structure:
    """A structure with ``nodes`` living nodes — enough for the voice to read."""
    base = structure.germinate(seed, generation=generation)
    extra = tuple(
        dataclasses.replace(base.nodes[0], id=index, parent_id=index - 1)
        for index in range(1, nodes)
    )
    return dataclasses.replace(base, nodes=base.nodes + extra, step_count=nodes)


def _state(**overrides) -> VoiceState:
    """A voice state with sensible defaults, for the pool-coverage checks."""
    fields = {
        "seed": 999,
        "mood": Mood.STEADY,
        "chapter": Chapter.YOUNG,
        "generation": 1,
        "blooming": False,
        "seeded": False,
        "hosting": False,
    }
    fields.update(overrides)
    return VoiceState(**fields)


# --- Determinism ---------------------------------------------------------------


def test_same_state_always_speaks_the_same_words():
    """Reading the same plant twice yields exactly the same lines."""
    plant = _plant(200)
    first = voice.read_state(plant, 0.5)
    second = voice.read_state(plant, 0.5)
    assert first == second
    assert voice.title(first) == voice.title(second)
    assert voice.passage(first) == voice.passage(second)


def test_selection_survives_a_new_process():
    """The same seed and state pick the same line in a freshly started interpreter.

    Guards the one mistake that would look fine in a single test run and break in
    production: selecting with the built-in ``hash()``, whose salt is randomised
    per process, so every restart would silently re-roll every plant's words.
    """
    state = _state(seed=4242, mood=Mood.WITHERED, chapter=Chapter.OLD)
    script = (
        "import voice;"
        "from voice import Chapter, Mood, VoiceState;"
        "state = VoiceState(seed=4242, mood=Mood.WITHERED, chapter=Chapter.OLD,"
        " generation=1, blooming=False, seeded=False, hosting=False);"
        "print(voice.passage(state))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == voice.passage(state)


def test_different_seeds_usually_speak_differently():
    """Two plants in the identical condition are not condemned to the same words."""
    passages = {voice.passage(_state(seed=seed)) for seed in range(40)}
    assert len(passages) > 1


def test_germination_greeting_is_seeded_and_stable():
    """A given seed always gets the same first words, and seeds do differ."""
    assert voice.germination_greeting(7) == voice.germination_greeting(7)
    assert len({voice.germination_greeting(seed) for seed in range(40)}) > 1


# --- Tick stability ------------------------------------------------------------


def test_a_routine_tick_does_not_change_the_words():
    """Growth within one chapter, at an unchanged moisture band, says the same thing.

    This is the whole tick-stability rule: the living message is re-rendered on
    every heartbeat, and re-rendering must not read as the plant changing its mind.
    """
    before = voice.read_state(_plant(200), 0.50)
    after = voice.read_state(_plant(230), 0.55)  # grown a step, same mood, same chapter
    assert (after.mood, after.chapter) == (before.mood, before.chapter)
    assert voice.title(after) == voice.title(before)
    assert voice.passage(after) == voice.passage(before)


def test_a_new_chapter_changes_the_words():
    """Growing into the next size class is a transition worth re-phrasing for."""
    established = voice.read_state(_plant(200), 0.5)
    mature = voice.read_state(_plant(600), 0.5)
    assert (established.chapter, mature.chapter) == (Chapter.ESTABLISHED, Chapter.MATURE)
    assert voice.passage(mature) != voice.passage(established)


def test_crossing_a_moisture_band_changes_the_words():
    """Drying out of one stage into the next is a transition worth re-phrasing for."""
    healthy = voice.read_state(_plant(200), 0.50)
    dry = voice.read_state(_plant(200), 0.30)
    assert dry.mood is Mood.DRY and healthy.mood is Mood.STEADY
    assert voice.passage(dry) != voice.passage(healthy)


# --- Reading the state ---------------------------------------------------------


def test_a_fresh_seedling_speaks_as_one_however_dry_it_is():
    """A founding plant germinates at zero moisture; it must not mourn lost wood."""
    assert voice.read_state(_plant(1), moisture.MIN_MOISTURE).mood is Mood.SEEDLING


def test_a_successor_seedling_knows_it_is_not_the_first():
    """The same tiny body speaks differently once it stands in a predecessor's soil."""
    assert voice.read_state(_plant(1, generation=3), 0.0).mood is Mood.REBORN


def test_the_dieback_band_has_its_own_mood():
    """Below the dieback threshold the drought costs wood, and the plant says so."""
    below = structure.DIEBACK_MOISTURE_THRESHOLD / 2
    assert voice.read_state(_plant(200), below).mood is Mood.PARCHED
    above = (structure.DIEBACK_MOISTURE_THRESHOLD + moisture.WITHERED_MAX) / 2
    assert voice.read_state(_plant(200), above).mood is Mood.WITHERED


def test_a_dead_plant_outranks_every_other_mood():
    """Death is read from the body, not from the moisture that caused it."""
    plant = _plant(50)
    dead = dataclasses.replace(
        plant,
        nodes=tuple(
            dataclasses.replace(node, state=structure.NodeState.DEAD) for node in plant.nodes
        ),
    )
    assert voice.read_state(dead, 1.0).mood is Mood.DEAD


def test_every_moisture_stage_maps_to_a_mood():
    """No stage may fall through to a default — each has its own register."""
    assert set(voice._STAGE_MOODS) == set(moisture.Stage)


# --- Pool coverage -------------------------------------------------------------


def test_every_mood_has_a_title_and_a_passage_pool():
    """No mood may be reachable without words for it."""
    for mood in Mood:
        state = _state(mood=mood)
        assert voice.title(state)
        assert voice.passage(state)


def test_every_chapter_speaks_without_a_body_line_only_where_intended():
    """Every chapter past seedling adds a body line; seedling and death do not."""
    for chapter in Chapter:
        spoken = voice.passage(_state(chapter=chapter))
        assert spoken
        has_body_line = chapter in voice._CHAPTERS
        assert has_body_line == (chapter is not Chapter.SEEDLING)
        assert (spoken != voice._pick(voice._MOODS[Mood.STEADY], _state(chapter=chapter), "mood")) == has_body_line
    assert voice.passage(_state(mood=Mood.DEAD, chapter=Chapter.ANCIENT)) in voice._MOODS[Mood.DEAD]


def test_every_milestone_has_words():
    """Bloom, seed and epiphyte each speak, and each speaks only when carried."""
    assert voice.milestone_lines(_state()) == []
    assert len(voice.milestone_lines(_state(blooming=True, seeded=True, hosting=True))) == 3
    for field in ("blooming", "seeded", "hosting"):
        assert len(voice.milestone_lines(_state(**{field: True}))) == 1


def test_the_pools_are_wide_enough_to_watch_daily():
    """Every pool holds enough distinct lines that a month of watching stays fresh."""
    pools = (
        list(voice._TITLES.values())
        + list(voice._MOODS.values())
        + list(voice._CHAPTERS.values())
        + [voice._BLOOM, voice._SEEDED, voice._HOSTING, voice._GERMINATION]
    )
    for pool in pools:
        assert len(pool) >= 8
        assert len(set(pool)) == len(pool)


def test_the_plant_never_breaks_character():
    """No line may name the machinery the plant is not supposed to know about."""
    forbidden = {
        "discord", "channel", "channels", "server", "servers", "message", "messages",
        "bot", "bots", "command", "commands", "guild", "guilds", "moisture", "tick",
        "ticks", "embed", "user", "users",
    }
    everything = [
        line
        for pool in (
            list(voice._TITLES.values())
            + list(voice._MOODS.values())
            + list(voice._CHAPTERS.values())
            + [voice._BLOOM, voice._SEEDED, voice._HOSTING, voice._GERMINATION]
        )
        for line in pool
    ]
    for line in everything:
        lowered = line.lower()
        named = forbidden & set(re.findall(r"[a-z]+", lowered))
        assert not named, f"{line!r} breaks character on {named}"
        assert "the plant" not in lowered, f"{line!r} speaks about itself in the third person"


def test_no_heading_stutters_into_its_own_passage():
    """A heading may not repeat, word for word, a phrase from the mood beneath it.

    The heading and the passage are drawn independently, so any phrasing shared
    between the two pools will eventually surface stacked on itself and read as a
    stutter. Single-word headings are exempt: they work as a label, not a phrase.
    """
    for mood, titles in voice._TITLES.items():
        lines = " ".join(voice._MOODS[mood]).lower()
        for title in titles:
            phrase = title.split(" ", 1)[1].lower().rstrip(".,")
            if len(phrase.split()) < 2:
                continue
            assert phrase not in lines, f"{title!r} repeats itself in the {mood.value} passage"


def test_presence_lines_are_all_mappable():
    """Every status line names an activity kind the adapter knows how to send."""
    assert voice.PRESENCE_LINES
    for kind, text in voice.PRESENCE_LINES:
        assert kind in ("playing", "watching", "listening")
        assert text
