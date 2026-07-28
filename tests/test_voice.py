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
        "vivid_bloom": False,
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
        " generation=1, blooming=False, seeded=False, hosting=False, vivid_bloom=False);"
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


def test_vivid_bloom_speaks_from_its_own_pool():
    """A vivid bloom's words come from a different, distinct pool than a modest one.

    Both are still bloom lines — the mechanism behind the difference (reaction
    warmth) is never named — but a reader should be able to tell the two apart.
    """
    modest = voice.milestone_lines(_state(blooming=True, vivid_bloom=False))[0]
    vivid = voice.milestone_lines(_state(blooming=True, vivid_bloom=True))[0]
    assert modest in voice._BLOOM_MODEST
    assert vivid in voice._BLOOM_VIVID
    assert modest not in voice._BLOOM_VIVID
    assert vivid not in voice._BLOOM_MODEST


def test_the_pools_are_wide_enough_to_watch_daily():
    """Every pool holds enough distinct lines that a month of watching stays fresh."""
    pools = (
        list(voice._TITLES.values())
        + list(voice._MOODS.values())
        + list(voice._CHAPTERS.values())
        + [
            voice._BLOOM_VIVID, voice._BLOOM_MODEST, voice._SEEDED, voice._HOSTING,
            voice._GERMINATION, voice._RING_TITLES, voice._RINGS,
        ]
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
            + [
            voice._BLOOM_VIVID, voice._BLOOM_MODEST, voice._SEEDED, voice._HOSTING,
            voice._GERMINATION, voice._RING_TITLES, voice._RINGS,
        ]
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


def test_the_cross_section_speaks_without_counting_or_stuttering():
    """The ring lines are drawn from the same seed as the heading over them, so
    the two must not share a phrase — and neither may ever state the number of
    years, which is the instrument field's job and not the plant's (a plant does
    not count itself, and the persona forbids numbers in speech)."""
    import re as _re

    passages = " ".join(voice._RINGS).lower()
    for title in voice._RING_TITLES:
        phrase = title.split(" ", 1)[1].lower().rstrip(".,")
        assert phrase not in passages, f"{title!r} repeats itself in a ring passage"
    for line in voice._RING_TITLES + voice._RINGS:
        assert not _re.search(r"\d", line), f"{line!r} states a number"


def test_the_cross_section_never_disturbs_what_the_plant_says_otherwise():
    """The tick-stability reason the ring pools sit outside ``VoiceState``: a
    plant showing its rings must still be speaking its ordinary lines underneath,
    unchanged, so the day the record opens and the day it closes are not read as
    a general change of mood."""
    plant = _plant(300, seed=99)
    state = voice.read_state(plant, 0.5)
    before = (voice.title(state), voice.passage(state), voice.milestone_lines(state))
    voice.ring_title(plant.seed, 3)
    voice.ring_passage(plant.seed, 3)
    assert (voice.title(state), voice.passage(state), voice.milestone_lines(state)) == before


def test_ring_lines_are_stable_within_a_showing_and_move_between_years():
    """Chosen from the seed and the year count, so the words cannot drift while
    the record is on show — the count does not change during it — and a later
    year's showing usually reads differently."""
    assert voice.ring_passage(4242, 3) == voice.ring_passage(4242, 3)
    assert len({voice.ring_passage(4242, count) for count in range(1, 12)}) > 1
    assert len({voice.ring_passage(seed, 3) for seed in range(40)}) > 1


def test_presence_lines_are_all_mappable():
    """Every status line names an activity kind the adapter knows how to send."""
    assert voice.PRESENCE_LINES
    for kind, text in voice.PRESENCE_LINES:
        assert kind in ("playing", "watching", "listening")
        assert text
