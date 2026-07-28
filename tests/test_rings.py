"""Tests for the tree rings: the plant's finished years, drawn as a cross-section.

This is the first phase that adds no vitality signal, and the first property
below is that claim itself — the rings must be provably unable to reach growth,
not merely observed not to. Everything after that is about the record being
honest: a year in progress is not a ring, a year nobody observed is not a ring,
a good year is wider and darker than a bad one, and a year that cost the plant
wood is marked with exactly the same event that left the grey branches on the
ordinary picture.

The write path gets its own section, because a record kept for years is only
worth as much as its worst restart: the tick that accumulates a year has to be
unable to double-count or skip one, whatever the bot does around a year boundary.

The last section is the only one that draws, in the narrowly-scoped exception
``CLAUDE.md`` permits: "an intense year is darker than a quiet one" is a promise
about pixels and cannot be stated in pure logic.
"""

import asyncio
import inspect
import itertools
import time
from unittest.mock import AsyncMock

from PIL import Image

import bot
import moisture
import render
import storage
import structure
from structure import (
    RING_MIN_TICKS,
    YearRecord,
    calendar_year,
    dead_node_count,
    genome_from_seed,
    germinate,
    grow,
    ring_layout,
    rings,
)

#: A year's worth of ticks, comfortably past ``RING_MIN_TICKS``.
FULL_YEAR_TICKS = 8760


def _year(year: int, vitality: float, *, ticks: int = FULL_YEAR_TICKS, wood_lost: int = 0):
    """A year record whose mean vitality is exactly ``vitality``."""
    return YearRecord(year=year, ticks=ticks, moisture_sum=vitality * ticks, wood_lost=wood_lost)


def _unix(year: int, month: int = 6, day: int = 15) -> float:
    """A Unix timestamp inside a given UTC calendar year."""
    import datetime

    return datetime.datetime(year, month, day, tzinfo=datetime.timezone.utc).timestamp()


# --- This is not a vitality signal ---------------------------------------------
#
# The whole phase rests on the rings being a second picture of data the plant has
# already lived through, never a sixth thing that shapes it. That is a structural
# claim, so it is checked structurally rather than by sampling behaviour.


def test_no_ring_function_can_reach_growth():
    """``grow`` takes no ring argument and the ring functions take no body, so
    there is no term through which a record could ever feed back into the plant
    it is a record of. The same proof-by-signature the voice-activity phase used,
    which is what makes this a picture rather than a signal."""
    assert set(inspect.signature(grow).parameters) == {
        "structure", "genome", "moisture", "steps",
        "breadth", "rhythm", "reaction_warmth", "thread_depth",
    }
    assert set(inspect.signature(rings).parameters) == {"records", "current_year"}
    assert set(inspect.signature(ring_layout).parameters) == {"rings"}


def test_a_body_grows_identically_whatever_its_record_says():
    """Stated the other way round: two plants given wildly different yearly
    records grow the same body from the same weather, because the record is not
    an input to anything that grows."""
    genome = genome_from_seed(4242)
    body = grow(germinate(4242), genome, 0.8, 300)
    assert rings([_year(2026, 0.9)], 2027) != rings([_year(2026, 0.05)], 2027)
    assert grow(germinate(4242), genome, 0.8, 300) == body


# --- What counts as a ring -----------------------------------------------------


def test_the_year_in_progress_is_not_a_ring_yet():
    """A ring is finished wood. The current year has no final vitality and no
    width, so it is never drawn — the outermost ring is always last year."""
    records = [_year(2026, 0.5), _year(2027, 0.5), _year(2028, 0.5)]
    assert [ring.year for ring in rings(records, 2028)] == [2026, 2027]


def test_a_year_nobody_watched_is_dropped_rather_than_guessed_at():
    """A plant that germinated in December, or a year the bot spent almost
    entirely offline, has no measurable ring. Drawing one from a handful of
    samples would claim more history than exists, so the year is left out."""
    barely = _year(2026, 0.9, ticks=RING_MIN_TICKS - 1)
    assert rings([barely], 2027) == ()
    assert len(rings([_year(2026, 0.9, ticks=RING_MIN_TICKS)], 2027)) == 1


def test_rings_read_from_the_pith_outward():
    """Oldest first, which is the order a trunk is actually read in — and the
    order ``ring_layout`` then places from the centre outward."""
    records = [_year(2028, 0.4), _year(2026, 0.4), _year(2027, 0.4)]
    assert [ring.year for ring in rings(records, 2029)] == [2026, 2027, 2028]


def test_a_rings_vitality_is_that_years_mean_moisture():
    """The year's own average, absolute rather than normalised against its
    neighbours — a life of uniformly middling years must read as middling, not
    be flattered by having nothing better to sit beside."""
    (ring,) = rings([_year(2026, 0.63)], 2027)
    assert abs(ring.vitality - 0.63) < 1e-9

    quiet, lush = rings([_year(2026, 0.1), _year(2027, 0.9)], 2028)
    later_life = rings([_year(2026, 0.1), _year(2027, 0.9), _year(2028, 1.0)], 2029)
    assert (quiet.vitality, lush.vitality) == (later_life[0].vitality, later_life[1].vitality)


def test_calendar_years_are_utc_and_agree_with_the_boundary():
    """One bucketing, shared with ``bot.py``, and UTC — a guild's year must not
    turn at a different moment depending on where its members live."""
    assert calendar_year(_unix(2026)) == 2026
    assert calendar_year(_unix(2026, 12, 31)) == 2026
    assert calendar_year(_unix(2026, 12, 31) + 86400) == 2027


# --- Scar rings are the drought that already happened --------------------------


def test_a_year_is_scarred_exactly_when_it_cost_the_plant_wood():
    """Not a second drought threshold applied to the same moisture: the flag
    reads the wood the dieback actually killed, so a scar ring can never
    disagree with the grey branches on the ordinary picture."""
    marked, clean = rings([_year(2026, 0.2, wood_lost=7), _year(2027, 0.2)], 2028)
    assert marked.scarred and not clean.scarred


def test_the_wood_a_scar_ring_counts_is_the_dieback_phase_7_performs():
    """End to end through the real growth model, which is the only way to show
    the two readings are one event: grow a body, drive it under the dieback
    threshold, and confirm the count ``bot.py`` records is exactly the wood
    ``grow`` turned to scars."""
    genome = genome_from_seed(99)
    healthy = grow(germinate(99), genome, 0.9, 200)
    assert dead_node_count(healthy) == 0

    parched = grow(healthy, genome, 0.0, 40)
    lost = dead_node_count(parched) - dead_node_count(healthy)
    assert lost > 0
    assert lost == sum(
        1 for node in parched.nodes if node.state is structure.NodeState.DEAD
    )
    (ring,) = rings([_year(2026, 0.0, wood_lost=lost)], 2027)
    assert ring.scarred


def test_a_dry_year_that_never_killed_wood_is_not_a_scar_year():
    """Thirst is not a scar. A year spent dry but always above the dieback
    threshold leaves a thin, pale ring — not a grey one — because nothing about
    it was permanent."""
    genome = genome_from_seed(7)
    body = grow(germinate(7), genome, 0.9, 200)
    dry = grow(body, genome, structure.DIEBACK_MOISTURE_THRESHOLD + 0.01, 40)
    lost = dead_node_count(dry) - dead_node_count(body)
    assert lost == 0
    (ring,) = rings([_year(2026, 0.09, wood_lost=lost)], 2027)
    assert not ring.scarred and ring.vitality < 0.2


# --- The layout: a fixed disc the years share out ------------------------------


def test_the_bands_are_contiguous_and_fill_the_trunk():
    """No gap between one year and the next, because there was none in the
    plant's life, and the outermost year meets the bark exactly."""
    bands = ring_layout(rings([_year(y, 0.3 + 0.2 * i) for i, y in enumerate(range(2020, 2028))], 2028))
    assert bands[0][0] == 0.0
    assert bands[-1][1] == 1.0
    for (_, outer), (inner, _) in itertools.pairwise(bands):
        assert outer == inner


def test_a_good_year_lays_down_a_wider_band_than_a_poor_one():
    """The one place a ring is read relative to its neighbours, and where it
    belongs — reading a cross-section is exactly that comparison."""
    lean, fat = ring_layout(rings([_year(2026, 0.05), _year(2027, 0.95)], 2028))
    assert (fat[1] - fat[0]) > (lean[1] - lean[0])


def test_even_the_worst_year_stays_thick_enough_to_see():
    """A year the plant lived through at all laid down some wood. Without the
    floor a single bad year among good ones would collapse to nothing, and the
    picture would say "this did not happen" where the truth is "this went
    badly"."""
    records = [_year(2026, 1.0), _year(2027, 0.0)] + [_year(y, 1.0) for y in range(2028, 2034)]
    bands = ring_layout(rings(records, 2034))
    worst = bands[1]
    assert (worst[1] - worst[0]) > 0.02


def test_more_years_share_the_same_trunk_between_them():
    """The disc is a fixed size, so a long life shows every year thinner than a
    short one does. That is what a real cross-section does, and it is why the
    absolute severity of a year lives in its colour rather than its width."""
    short = ring_layout(rings([_year(2026, 0.5), _year(2027, 0.5)], 2028))
    long = ring_layout(rings([_year(y, 0.5) for y in range(2020, 2028)], 2028))
    assert (long[0][1] - long[0][0]) < (short[0][1] - short[0][0])


def test_a_plant_with_nothing_finished_has_no_layout_to_draw():
    """The young-plant case, stated where it is decided: no rings, no bands, and
    no half-invented first ring standing in for a year nobody measured."""
    assert rings([], 2026) == ()
    assert ring_layout(()) == ()


# --- The write path: a record is only as good as its worst restart -------------


def _storage(tmp_path) -> storage.Storage:
    return storage.Storage(str(tmp_path / "rings.db"))


def test_a_year_accumulates_one_tick_at_a_time(tmp_path):
    """The record is a byproduct of ticks that already happened, never a
    reconstruction: three ticks make a year of three ticks, and the vitality
    they ran at averages out to what they ran at."""
    store = _storage(tmp_path)
    for value in (0.2, 0.4, 0.6):
        store.record_year_tick(1, 2026, value, 0)
    record = store.load_all_yearly_rings()[1][2026]
    assert record.ticks == 3
    assert abs(record.moisture_sum - 1.2) < 1e-9
    store.close()


def test_a_restart_at_a_year_boundary_neither_skips_nor_doubles_a_year(tmp_path):
    """The failure this write path is shaped against. Ticks land either side of
    a boundary, the process dies, and a fresh Storage over the same file picks
    up both years exactly where they were — because each tick is one atomic
    accumulating upsert, not a read-modify-write with a window in it."""
    path = str(tmp_path / "restart.db")
    first = storage.Storage(path)
    for _ in range(5):
        first.record_year_tick(1, 2026, 0.5, 0)
    first.record_year_tick(1, 2027, 0.5, 0)
    first.close()  # the bot goes down mid-January

    second = storage.Storage(path)
    for _ in range(3):
        second.record_year_tick(1, 2027, 0.5, 0)
    years = second.load_all_yearly_rings()[1]
    assert years[2026].ticks == 5
    assert years[2027].ticks == 4
    second.close()


def test_a_year_the_bot_never_saw_leaves_no_row_at_all(tmp_path):
    """A year spent entirely offline is absent rather than recorded as a bad
    one. ``rings`` reads that as "not observed" and draws nothing for it, which
    is the honest reading — nobody was there to say how the server was."""
    store = _storage(tmp_path)
    store.record_year_tick(1, 2026, 0.5, 0)
    store.record_year_tick(1, 2028, 0.5, 0)
    assert set(store.load_all_yearly_rings()[1]) == {2026, 2028}
    store.close()


def test_a_successors_trunk_carries_none_of_its_predecessors_years(tmp_path):
    """Rings side with the presence tables, not the counters: no cross-section
    can contain a year in which this body did not exist."""
    store = _storage(tmp_path)
    store.record_year_tick(1, 2026, 0.5, 0)
    store.record_year_tick(2, 2026, 0.5, 0)
    store.clear_yearly_rings(1)
    loaded = store.load_all_yearly_rings()
    assert 1 not in loaded and 2 in loaded
    store.close()


# --- The trigger: once a year, for a day, with nothing stored to make it so ----


def _client_with_years(guild_id: int, years: dict[int, YearRecord]) -> bot.EpiphyteClient:
    """A client holding a guild's year records and nothing else it needs here."""
    client = bot.EpiphyteClient()
    client._yearly[guild_id] = dict(years)
    return client


def test_the_window_opens_when_the_year_turns_and_closes_by_itself():
    """The whole trigger, and it stores no anniversary to be one: the current
    year's own observed tick count is how long ago that year began."""
    lived = {2026: _year(2026, 0.6), 2027: _year(2027, 0.6)}
    now = _unix(2028, 1, 1)

    just_turned = _client_with_years(1, {**lived, 2028: _year(2028, 0.6, ticks=1)})
    assert len(just_turned._cross_section(1, now)) == 2

    last_hour = _client_with_years(1, {**lived, 2028: _year(2028, 0.6, ticks=bot.RING_DISPLAY_TICKS)})
    assert len(last_hour._cross_section(1, now)) == 2

    over = _client_with_years(1, {**lived, 2028: _year(2028, 0.6, ticks=bot.RING_DISPLAY_TICKS + 1)})
    assert over._cross_section(1, now) == ()


def test_a_young_server_never_shows_a_cross_section():
    """The first tick of a plant's life lands in the window by definition, so
    this is the case that has to be right: no finished year, nothing to show,
    and the ordinary picture instead of a broken one."""
    first_tick = _client_with_years(1, {2026: _year(2026, 0.0, ticks=1)})
    assert first_tick._cross_section(1, _unix(2026, 1, 1)) == ()

    germinated_in_december = _client_with_years(
        1, {2026: _year(2026, 0.6, ticks=200), 2027: _year(2027, 0.6, ticks=1)}
    )
    assert germinated_in_december._cross_section(1, _unix(2027, 1, 1)) == ()


def test_reading_the_window_never_writes_anything():
    """``/plant`` calls this outside the tick, so it has to be safe at any
    moment — the same rule ``_voice_activity`` follows."""
    client = _client_with_years(1, {2026: _year(2026, 0.6), 2027: _year(2027, 0.6, ticks=1)})
    before = dict(client._yearly[1])
    client._cross_section(1, _unix(2027, 1, 1))
    assert client._yearly[1] == before


def test_a_tick_folds_itself_into_its_year_and_records_the_wood_it_cost():
    """``advance_life``'s side of the record, driven through the real method:
    the vitality the step ran at and the dieback that step performed, not a
    second measurement of either."""
    client = bot.EpiphyteClient()
    guild_id = 1
    genome = genome_from_seed(99)
    body = grow(germinate(99), genome, 0.9, 200)
    now = _unix(2026, 3, 1)
    client._states[guild_id] = storage.GuildState(
        guild_id=guild_id,
        structure=body,
        moisture=0.0,  # fully dried out: this tick is a dieback step
        last_update=now,
        channel_id=100,
        message_id=None,
    )

    asyncio.run(client.advance_life(guild_id, now))

    record = client._yearly[guild_id][2026]
    assert record.ticks == 1
    assert record.moisture_sum == 0.0
    assert record.wood_lost == dead_node_count(client._states[guild_id].structure)
    assert record.wood_lost > 0


def test_a_rebirth_wipes_the_record_with_the_presence_tables():
    """Wired through ``advance_life``'s own death branch rather than asserted on
    the helper, so the wipe is shown to actually happen where it matters."""
    client = bot.EpiphyteClient()
    guild_id = 1
    genome = genome_from_seed(5)
    # A germ that never grew lies dormant rather than dying, so the plant has to
    # have a body before a drought can take all of it.
    dead = grow(grow(germinate(5), genome, 0.9, 150), genome, 0.0, 600)
    assert structure.is_dead(dead)
    now = _unix(2027, 5, 1)
    client._states[guild_id] = storage.GuildState(
        guild_id=guild_id,
        structure=dead,
        moisture=0.0,
        last_update=now,
        channel_id=100,
        message_id=None,
        dead_ticks=bot.DEAD_PHASE_TICKS - 1,
    )
    client._yearly[guild_id] = {2026: _year(2026, 0.6)}

    asyncio.run(client.advance_life(guild_id, now))

    assert client._states[guild_id].structure.generation == 2
    assert client._yearly.get(guild_id, {}) == {}


def _refresh_at(client: bot.EpiphyteClient, guild_id: int, moment: float) -> list[tuple]:
    """Run one living-message refresh with the clock pinned, capturing what it
    asked the renderer for."""
    channel = AsyncMock()
    channel.send = AsyncMock(return_value=AsyncMock(id=555))
    client._text_channel = AsyncMock(return_value=channel)
    asked: list[tuple] = []

    async def _capture(plant, moisture_value, voice_activity=0.0, rings=(), wind=False):
        asked.append(rings)
        return b"fake-png"

    client._render_bytes = _capture
    real_time = time.time
    time.time = lambda: moment
    try:
        asyncio.run(client.refresh_channel_message(guild_id))
    finally:
        time.time = real_time
    return asked


def test_the_living_message_shows_the_record_only_inside_the_window():
    """The wiring end to end: on ring day the refresh renders the cross-section,
    and on an ordinary day it renders the plant — decided entirely by the window,
    with nothing stored to remember which."""
    guild_id = 1
    lived = {2026: _year(2026, 0.6), 2027: _year(2027, 0.6)}
    state = storage.GuildState(
        guild_id=guild_id,
        structure=germinate(1),
        moisture=moisture.MIN_MOISTURE,
        last_update=0.0,
        channel_id=100,
        message_id=None,
    )

    on_ring_day = _client_with_years(guild_id, {**lived, 2028: _year(2028, 0.6, ticks=1)})
    on_ring_day._states[guild_id] = state
    assert len(_refresh_at(on_ring_day, guild_id, _unix(2028, 1, 1))[0]) == 2

    ordinary = _client_with_years(guild_id, {**lived, 2028: _year(2028, 0.6, ticks=500)})
    ordinary._states[guild_id] = state
    assert _refresh_at(ordinary, guild_id, _unix(2028, 1, 1))[0] == ()


# --- "Denser and darker" as measured pixels, not adjectives --------------------
#
# The only tests here that draw. A ring's colour is a promise about the image
# and cannot be stated in pure logic; see the module docstring.


def _band_color(image: Image.Image, fraction: float) -> tuple[int, ...]:
    """The colour on the horizontal radius at ``fraction`` of the wood's reach."""
    center = image.width // 2
    disc = image.width / 2 - render._RING_PADDING / render.SUPERSAMPLE
    wood = disc * (1.0 - render._RING_BARK_SHARE)
    pixel = image.getpixel((int(center + wood * fraction), center))
    assert isinstance(pixel, tuple)
    return pixel


def _luminance(color: tuple[int, ...]) -> float:
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def test_an_intense_year_renders_darker_than_a_quiet_one():
    """Dense, dark late wood for a year of sustained health; pale, open wood for
    a quiet stretch. Sampled inside each of two equal bands, so the reading is
    the colour rather than the width."""
    quiet_first = render.render_rings(
        rings([_year(2026, 0.05), _year(2027, 0.95)], 2028), seed=11
    )
    image = Image.open(quiet_first).convert("RGB")
    quiet = _band_color(image, 0.15)
    lush = _band_color(image, 0.85)
    assert _luminance(lush) < _luminance(quiet), f"{lush} should be darker than {quiet}"


def test_a_drought_year_is_drawn_in_the_same_grey_as_the_branches_it_killed():
    """One event, one colour: a scar ring is ``render.DEAD_WOOD``, exactly what
    the dead branches of that same drought are drawn in on the ordinary
    picture."""
    image = Image.open(
        render.render_rings(rings([_year(2026, 0.02, wood_lost=40)], 2027), seed=3)
    ).convert("RGB")
    assert render.RING_SCAR is render.DEAD_WOOD
    assert _band_color(image, 0.5) == render.DEAD_WOOD


def test_every_year_on_record_actually_appears_in_the_wood():
    """A ring nobody can find is not a record. Eight years of differing health
    all leave a distinguishable band rather than blending into their
    neighbours."""
    record = rings([_year(y, 0.1 + 0.1 * i) for i, y in enumerate(range(2018, 2026))], 2026)
    image = Image.open(render.render_rings(record, seed=77)).convert("RGB")
    bands = ring_layout(record)
    sampled = [_band_color(image, (inner + outer) / 2) for inner, outer in bands]
    assert len(set(sampled)) == len(record)


def test_a_trunk_keeps_its_silhouette_between_renders():
    """Seeded like the leaf placement and the blossom rotations: the same trunk
    is the same shape every year, and two trunks are not the same shape."""
    record = rings([_year(2026, 0.5), _year(2027, 0.8)], 2028)
    once = render.render_rings(record, seed=5).getvalue()
    assert render.render_rings(record, seed=5).getvalue() == once
    assert render.render_rings(record, seed=6).getvalue() != once


def test_the_plants_own_picture_is_untouched_by_any_of_this():
    """The separation, stated in bytes: ``render`` and ``render_rings`` are
    alternatives the caller chooses between, never layers, so nothing about the
    rings can leak into the plant's portrait."""
    genome = genome_from_seed(4242)
    body = grow(germinate(4242), genome, 0.8, 300)
    # ``wind`` (Phase 20) joined this list; ``rings`` never can. The point of
    # pinning the whole set is that a ring is not something the plant's own
    # picture is drawn *with*, however many other arguments it grows.
    assert set(inspect.signature(render.render).parameters) == {
        "structure", "moisture", "genome", "voice_activity", "wind",
    }
    assert render.render(body, 0.8, genome).getvalue() == render.render(body, 0.8, genome).getvalue()
