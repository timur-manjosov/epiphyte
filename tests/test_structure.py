"""Tests for the pure body logic. No Pillow, no Discord, no persistence.

Phase 5 properties: germination, seeded determinism and individuality, additive
growth, moisture-scaled growth, and a consistent tree topology. Phase 7 adds the
biography: drought kills wood from the outside in, dead wood is a permanent scar
that survives recovery, and the accumulated body never shrinks. Phase 8 adds the
lifecycle, and Phase 9 the milestones — bloom, seed and the epiphyte — which are
thresholds on the accumulated life statistics rather than stages on a timer.
"""

import dataclasses
import hashlib
import json

from structure import (
    BLOOM_HEALTHY_STEPS,
    BLOOM_MIN_NODES,
    BLOOM_VITALITY,
    BLOOM_WILT_VITALITY,
    BREADTH_SATURATION_VOICES,
    EPIPHYTE_MIN_AGE,
    EPIPHYTE_MIN_BLOOMS,
    EPIPHYTE_MIN_NODES,
    SEED_BLOOM_STEPS,
    LifeStats,
    NodeState,
    author_breadth,
    can_host_epiphyte,
    epiphyte_genome,
    genome_from_seed,
    germinate,
    germinate_successor,
    grow,
    has_seeded,
    is_blooming,
    is_dead,
    mutate,
    serialize,
)


def _count_state(structure, state) -> int:
    """Count the nodes in ``structure`` that are in ``state``."""
    return sum(1 for node in structure.nodes if node.state is state)


def _children(structure) -> dict[int, list[int]]:
    """Map each node id to its children's ids."""
    kids: dict[int, list[int]] = {}
    for node in structure.nodes:
        if node.parent_id is not None:
            kids.setdefault(node.parent_id, []).append(node.id)
    return kids


def _mean_angle_deviation(structure) -> float:
    """Average how far each non-germ node's angle wandered from its limb's own
    bearing — the exact quantity rhythm's jitter multiplier scales."""
    diffs = [abs(n.angle - n.axis_angle) for n in structure.nodes if n.parent_id is not None]
    return sum(diffs) / len(diffs)


def _grown(seed: int, moisture: float, steps: int):
    """Germinate ``seed`` and grow it ``steps`` steps under ``moisture``."""
    structure = germinate(seed)
    genome = genome_from_seed(seed)
    return grow(structure, genome, moisture, steps)


def test_germinate_is_a_single_tip() -> None:
    structure = germinate(7)
    assert len(structure.nodes) == 1
    germ = structure.nodes[0]
    assert germ.id == 0
    assert germ.parent_id is None
    assert germ.order == 0
    assert germ.state is NodeState.TIP
    assert structure.step_count == 0
    assert structure.seed == 7


def test_zero_steps_is_identity() -> None:
    structure = germinate(1)
    genome = genome_from_seed(1)
    assert serialize(grow(structure, genome, 1.0, 0)) == serialize(structure)


def test_same_seed_same_history_is_identical() -> None:
    assert serialize(_grown(42, 0.8, 12)) == serialize(_grown(42, 0.8, 12))


def test_different_seeds_grow_visibly_different_plants() -> None:
    a = _grown(1, 0.9, 12)
    b = _grown(2, 0.9, 12)
    assert serialize(a) != serialize(b)


def test_growth_is_additive() -> None:
    """Existing nodes are preserved verbatim; growth only appends new ones."""
    before = _grown(3, 0.7, 6)
    genome = genome_from_seed(3)
    after = grow(before, genome, 0.7, 4)

    assert len(after.nodes) >= len(before.nodes)
    for old in before.nodes:
        kept = after.nodes[old.id]
        assert kept.id == old.id
        assert kept.parent_id == old.parent_id
        assert (kept.x, kept.y) == (old.x, old.y)
        assert kept.angle == old.angle
        assert kept.order == old.order
        assert kept.birth_step == old.birth_step


def test_higher_moisture_grows_more() -> None:
    wet = _grown(5, 0.9, 12)
    dry = _grown(5, 0.1, 12)
    assert len(wet.nodes) > len(dry.nodes)


def test_step_count_advances_by_steps() -> None:
    structure = germinate(9)
    genome = genome_from_seed(9)
    grown = grow(structure, genome, 0.6, 7)
    assert grown.step_count == 7
    assert grow(grown, genome, 0.6, 3).step_count == 10


def test_growth_is_chunk_invariant() -> None:
    """Running the steps at once equals running them one at a time."""
    seed, moisture, steps = 11, 0.7, 8
    genome = genome_from_seed(seed)

    at_once = grow(germinate(seed), genome, moisture, steps)

    piecewise = germinate(seed)
    for _ in range(steps):
        piecewise = grow(piecewise, genome, moisture, 1)

    assert serialize(at_once) == serialize(piecewise)


def test_tree_topology_is_consistent() -> None:
    """Exactly one root; every other node has one existing, earlier parent."""
    structure = _grown(13, 0.85, 14)
    ids = {node.id for node in structure.nodes}

    roots = [node for node in structure.nodes if node.parent_id is None]
    assert len(roots) == 1
    assert roots[0].id == 0

    for node in structure.nodes:
        assert node.id == structure.nodes[node.id].id  # id equals list index
        if node.parent_id is not None:
            assert node.parent_id in ids
            assert node.parent_id < node.id  # acyclic: parents precede children


def test_serialize_round_trips() -> None:
    from structure import deserialize

    structure = _grown(21, 0.75, 10)
    assert serialize(deserialize(serialize(structure))) == serialize(structure)


# --- Phase 7: dieback and the biography --------------------------------------

#: A moderate drought — below the dieback threshold, but only nibbling the crown
#: (partial dieback with survivors), not the deep silence that kills the whole plant.
DROUGHT = 0.05


def test_drought_kills_wood_from_outside_in() -> None:
    """A sustained drought kills wood, and only from the outside in.

    A node dies only once all its children are already dead, so no dead node ever
    has a living descendant — dieback marches from the tips inward, never the
    reverse. The germ base is spared.
    """
    seed = 30
    healthy = _grown(seed, 0.7, 60)
    withered = grow(healthy, genome_from_seed(seed), DROUGHT, 40)

    assert _count_state(withered, NodeState.DEAD) > 0, "a drought must kill some wood"
    assert withered.nodes[0].state is not NodeState.DEAD, "the germ base survives"

    kids = _children(withered)
    for node in withered.nodes:
        if node.state is NodeState.DEAD:
            for child_id in kids.get(node.id, ()):
                assert withered.nodes[child_id].state is NodeState.DEAD


def test_dead_wood_persists_through_recovery() -> None:
    """Dead wood never revives: a drought's scar is still there after recovery."""
    seed = 31
    genome = genome_from_seed(seed)
    withered = grow(_grown(seed, 0.7, 60), genome, DROUGHT, 30)
    scar = {node.id for node in withered.nodes if node.state is NodeState.DEAD}
    assert scar, "a drought must leave a scar"

    recovered = grow(withered, genome, 0.9, 60)  # the rain returns
    for node_id in scar:
        assert recovered.nodes[node_id].state is NodeState.DEAD


def test_body_and_wood_never_shrink() -> None:
    """Across a whole life the body only accumulates.

    Through growth, drought, recovery and drought again, the node count never
    falls (nodes are never removed), the dead count never falls (dead stays dead),
    and lignified wood — living plus dead — never falls: the body is a monotonic
    record of the plant's history.
    """
    genome = genome_from_seed(32)
    structure = germinate(32)
    schedule = [(0.8, 40), (DROUGHT, 25), (0.9, 40), (0.0, 30)]

    prev_nodes = prev_wood = prev_dead = 0
    for moisture, steps in schedule:
        for _ in range(steps):
            structure = grow(structure, genome, moisture, 1)
            nodes = len(structure.nodes)
            dead = _count_state(structure, NodeState.DEAD)
            wood = _count_state(structure, NodeState.WOODY) + dead
            assert nodes >= prev_nodes
            assert dead >= prev_dead
            assert wood >= prev_wood
            prev_nodes, prev_wood, prev_dead = nodes, wood, dead

    assert prev_dead > 0, "the droughts should have left scars"


def test_longer_drought_reaches_further_in() -> None:
    """Continued drought kills more wood — dieback progresses inward over time."""
    seed = 33
    genome = genome_from_seed(seed)
    healthy = _grown(seed, 0.7, 60)
    short = grow(healthy, genome, DROUGHT, 10)
    long = grow(healthy, genome, DROUGHT, 45)
    assert _count_state(long, NodeState.DEAD) > _count_state(short, NodeState.DEAD)


def test_dieback_is_chunk_invariant() -> None:
    """Dying back N steps at once equals dying back the same steps one at a time."""
    seed = 34
    genome = genome_from_seed(seed)
    healthy = _grown(seed, 0.7, 50)

    at_once = grow(healthy, genome, DROUGHT, 20)
    piecewise = healthy
    for _ in range(20):
        piecewise = grow(piecewise, genome, DROUGHT, 1)

    assert serialize(at_once) == serialize(piecewise)


def test_partial_drought_recovers_with_living_tips() -> None:
    """A partial drought leaves both a scar and living tips that regrow on rain."""
    seed = 30
    genome = genome_from_seed(seed)
    withered = grow(_grown(seed, 0.7, 60), genome, DROUGHT, 15)

    assert _count_state(withered, NodeState.DEAD) > 0, "some wood should have died"
    assert _count_state(withered, NodeState.TIP) > 0, "some tips should survive"

    recovered = grow(withered, genome, 0.9, 40)
    assert len(recovered.nodes) > len(withered.nodes)  # new growth returns


# --- Phase 8: death, seed and lineage ----------------------------------------

#: A deep, unbroken silence that drives vitality to zero and kills the whole plant.
DEAD_SILENCE = 0.0


def test_mutate_is_deterministic_and_different() -> None:
    """A mutation is reproducible and always yields a different seed."""
    for seed in (0, 1, 42, 123456789, (1 << 62) + 7):
        assert mutate(seed) == mutate(seed)
        assert mutate(seed) != seed


def test_mutate_resembles_the_parent() -> None:
    """A single-gene mutation changes exactly one genome trait; the rest carry over."""
    for seed in (42, 777, 20260101):
        parent = genome_from_seed(seed)
        child = genome_from_seed(mutate(seed))
        differing = sum(
            1
            for field in dataclasses.fields(parent)
            if getattr(parent, field.name) != getattr(child, field.name)
        )
        assert differing == 1


def test_is_dead_recognises_a_fully_dead_body() -> None:
    """``is_dead`` is true only when every node is dead."""
    assert not is_dead(germinate(5))  # a fresh germ is alive
    assert not is_dead(_grown(5, 0.7, 40))  # a growing plant is alive
    dead = grow(_grown(5, 0.7, 60), genome_from_seed(5), DEAD_SILENCE, 300)
    assert is_dead(dead)


def test_sustained_silence_kills_the_whole_plant() -> None:
    """A partial drought spares the base; an unrelenting one kills it too."""
    seed = 42
    genome = genome_from_seed(seed)
    healthy = _grown(seed, 0.7, 60)

    partial = grow(healthy, genome, DROUGHT, 20)
    assert not is_dead(partial)  # Phase 7: the base survives a moderate drought
    assert partial.nodes[0].state is not NodeState.DEAD

    fully = grow(healthy, genome, DEAD_SILENCE, 300)
    assert is_dead(fully)  # Phase 8: deep silence reaches even the germ
    assert fully.nodes[0].state is NodeState.DEAD


def test_dormant_germ_survives_drought() -> None:
    """A germ that never grew lies dormant as a seed; drought cannot kill it."""
    germ = germinate(999)
    parched = grow(germ, genome_from_seed(999), DEAD_SILENCE, 200)
    assert not is_dead(parched)
    assert len(parched.nodes) == 1  # still just the waiting seed


def test_germinate_successor_is_a_mutated_child() -> None:
    """A successor is a fresh germ from a mutated seed, one generation on."""
    genome = genome_from_seed(42)
    dead = grow(_grown(42, 0.7, 60), genome, DEAD_SILENCE, 300)
    assert is_dead(dead)

    child = germinate_successor(dead)
    assert len(child.nodes) == 1  # a fresh single germ
    assert child.nodes[0].state is NodeState.TIP
    assert child.step_count == 0
    assert child.seed == mutate(dead.seed)
    assert child.seed != dead.seed
    assert child.parent_seed == dead.seed
    assert child.generation == dead.generation + 1


def test_generation_climbs_across_a_lineage() -> None:
    """Each successor carries the lineage forward with a rising generation."""
    plant = germinate(7)
    assert plant.generation == 1 and plant.parent_seed is None

    seeds = [plant.seed]
    for expected_generation in (2, 3, 4):
        plant = germinate_successor(plant)
        assert plant.generation == expected_generation
        assert plant.parent_seed == seeds[-1]
        seeds.append(plant.seed)

    assert len(set(seeds)) == len(seeds)  # every generation is its own individual


# --- Phase 9: bloom, seed and the epiphyte ------------------------------------

#: Vitality a lively channel holds — comfortably inside the band that banks health.
TENDED = 0.75
#: A seed with genes spread across their ranges, as a real 63-bit seed gives. The
#: small seeds above sit at the bottom of every range, which grows a slow plant.
TENDED_SEED = 0x2F3A9C41D77E5B2


def test_short_activity_earns_no_milestone() -> None:
    """A busy few days triggers nothing — the milestones are not on a timer."""
    plant = _grown(TENDED_SEED, TENDED, 72)  # three days of hourly steps, all healthy
    assert not is_blooming(plant, TENDED)
    assert not has_seeded(plant)
    assert not can_host_epiphyte(plant)
    assert plant.epiphyte is None


def test_bloom_needs_banked_health_and_a_mature_body() -> None:
    """Both thresholds bind: neither a full bank nor a grown body flowers alone."""
    sapling = _grown(TENDED_SEED, TENDED, 100)
    assert len(sapling.nodes) < BLOOM_MIN_NODES
    banked = dataclasses.replace(sapling, stats=LifeStats(healthy_steps=BLOOM_HEALTHY_STEPS * 5))
    assert not is_blooming(banked, TENDED), "a young plant cannot flower, however tended"

    grown = _grown(TENDED_SEED, TENDED, 400)
    assert len(grown.nodes) >= BLOOM_MIN_NODES
    short = dataclasses.replace(grown, stats=LifeStats(healthy_steps=BLOOM_HEALTHY_STEPS - 1))
    assert not is_blooming(short, TENDED), "one step short of the bank is still no bloom"
    full = dataclasses.replace(grown, stats=LifeStats(healthy_steps=BLOOM_HEALTHY_STEPS))
    assert is_blooming(full, TENDED)


def test_bloom_holds_through_a_dip_but_not_a_decline() -> None:
    """An open bloom rides out the ordinary ebb; only a real decline takes it.

    A channel breathes — busy by day, quiet overnight — so the bloom deliberately
    survives falling back under the vitality that opened it, and is lost only when
    the plant is genuinely left to dry out.
    """
    genome = genome_from_seed(TENDED_SEED)
    flowering = grow(germinate(TENDED_SEED), genome, TENDED, BLOOM_HEALTHY_STEPS)
    assert is_blooming(flowering, TENDED)

    quiet_night = BLOOM_VITALITY - 0.1
    assert is_blooming(flowering, quiet_night), "a quiet night does not close the flowers"
    dipped = grow(flowering, genome, quiet_night, 12)
    assert dipped.stats.in_bloom

    declined = grow(dipped, genome, BLOOM_WILT_VITALITY - 0.05, 3)
    assert not declined.stats.in_bloom, "a real decline wilts it"
    assert declined.stats.healthy_steps < BLOOM_HEALTHY_STEPS, "flowering spent the bank"
    assert not is_blooming(declined, 1.0), "a spent bloom is not bought back with water"

    parched = grow(declined, genome, 0.1, 20)
    assert parched.stats.healthy_steps == declined.stats.healthy_steps, "the bank waits"


def test_bloom_ends_by_itself_and_is_earned_again() -> None:
    """Flowering spends the bank that bought it, so a season ends and another comes.

    This is what makes repeated blooming emerge from the rules: even under unbroken
    care the plant cannot stay in flower, and each further season has to be banked.
    """
    genome = genome_from_seed(TENDED_SEED)
    flowering = grow(germinate(TENDED_SEED), genome, TENDED, BLOOM_HEALTHY_STEPS)
    assert flowering.stats.bloom_count == 1 and flowering.stats.in_bloom

    spent = grow(flowering, genome, TENDED, BLOOM_HEALTHY_STEPS + 10)
    assert not is_blooming(spent, TENDED), "unbroken health does not hold a bloom open"
    assert spent.stats.bloom_count == 1

    again = grow(spent, genome, TENDED, BLOOM_HEALTHY_STEPS + 10)
    assert again.stats.bloom_count == 2


def test_seed_is_set_by_a_lasting_bloom_and_stays() -> None:
    """Seed is earned by a long flowering, and outlives the flowers themselves."""
    genome = genome_from_seed(TENDED_SEED)
    flowering = grow(germinate(TENDED_SEED), genome, TENDED, BLOOM_HEALTHY_STEPS)
    assert not has_seeded(flowering), "coming into bloom is not yet setting seed"

    seeded = grow(flowering, genome, TENDED, SEED_BLOOM_STEPS)
    assert has_seeded(seeded)

    parched = grow(seeded, genome, 0.0, 40)  # a drought takes the flowers
    assert not is_blooming(parched, 0.0)
    assert has_seeded(parched), "the seed it set stays on the body"


def test_bloom_colour_is_a_gene():
    """Blossom colour comes from the genome, so plants flower in different shades."""
    seeds = (0x11111111111111, TENDED_SEED, 0x7654321ABCDEF0)
    hues = {genome_from_seed(seed).bloom_hue for seed in seeds}
    assert len(hues) > 1, "different plants must flower differently"
    for seed in seeds:
        assert 0.0 <= genome_from_seed(seed).bloom_hue <= 1.0
        assert genome_from_seed(seed).bloom_hue == genome_from_seed(seed).bloom_hue


def _epiphyte_ready(steps: int = 800):
    """A tree grown large, then aged and credited with the flowerings it takes."""
    genome = genome_from_seed(TENDED_SEED)
    tree = grow(germinate(TENDED_SEED), genome, TENDED, steps)
    assert len(tree.nodes) >= EPIPHYTE_MIN_NODES, "the test tree must be large enough"
    return dataclasses.replace(
        tree,
        step_count=EPIPHYTE_MIN_AGE - 1,
        stats=LifeStats(bloom_count=EPIPHYTE_MIN_BLOOMS),
    )


def test_epiphyte_needs_age_and_size_and_repeated_blooms() -> None:
    """All three thresholds bind; no one of them alone lets an epiphyte take hold."""
    ready = _epiphyte_ready()
    old = dataclasses.replace(ready, step_count=EPIPHYTE_MIN_AGE)
    assert can_host_epiphyte(old)

    assert not can_host_epiphyte(ready), "one step short of old enough"
    assert not can_host_epiphyte(
        dataclasses.replace(old, stats=LifeStats(bloom_count=EPIPHYTE_MIN_BLOOMS - 1))
    ), "a tree that has not flowered often enough carries nothing"

    stunted = dataclasses.replace(
        _grown(TENDED_SEED, TENDED, 60),
        step_count=EPIPHYTE_MIN_AGE,
        stats=LifeStats(bloom_count=EPIPHYTE_MIN_BLOOMS),
    )
    assert len(stunted.nodes) < EPIPHYTE_MIN_NODES
    assert not can_host_epiphyte(stunted), "an old but stunted plant carries nothing"


def test_epiphyte_settles_on_an_old_limb_and_grows_on() -> None:
    """Once the thresholds are met an epiphyte takes hold, on old wood up the tree."""
    ready = _epiphyte_ready()
    assert ready.epiphyte is None
    genome = genome_from_seed(TENDED_SEED)

    settled = grow(ready, genome, TENDED, 1)
    assert settled.epiphyte is not None
    limb = settled.nodes[settled.epiphyte.host_node_id]
    assert limb.state is NodeState.WOODY  # living branch wood, not a dead scar
    assert limb.order >= 1  # a limb, not the trunk
    assert limb.birth_step <= settled.step_count / 2  # old wood, not this week's twig

    heights = [node.y for node in settled.nodes]
    span = max(heights) - min(heights)
    assert limb.y >= min(heights) + span * 0.3  # up in the crown, not at the foot

    older = grow(settled, genome, TENDED, 200)
    assert older.epiphyte is not None
    assert older.epiphyte.host_node_id == settled.epiphyte.host_node_id  # it stays put
    assert len(older.epiphyte.structure.nodes) > len(settled.epiphyte.structure.nodes)


def test_epiphyte_is_a_dwarfed_individual_of_its_own() -> None:
    """Its genome is derived from the host's seed, but is its own — and far smaller."""
    host = genome_from_seed(TENDED_SEED)
    guest = epiphyte_genome(TENDED_SEED)
    assert guest.vigor < host.vigor
    assert guest.internode_length < host.internode_length
    assert epiphyte_genome(TENDED_SEED) == guest  # deterministic
    assert epiphyte_genome(TENDED_SEED + 1) != guest  # and its own host's, not any host's


def test_milestones_are_chunk_invariant() -> None:
    """Bloom, seed and epiphyte come out the same at once as one step at a time."""
    genome = genome_from_seed(TENDED_SEED)
    ready = dataclasses.replace(
        _epiphyte_ready(),
        stats=LifeStats(healthy_steps=BLOOM_HEALTHY_STEPS, bloom_count=EPIPHYTE_MIN_BLOOMS),
    )

    at_once = grow(ready, genome, TENDED, 60)
    piecewise = ready
    for _ in range(60):
        piecewise = grow(piecewise, genome, TENDED, 1)

    assert serialize(at_once) == serialize(piecewise)


def test_a_plant_that_set_seed_enriches_its_line() -> None:
    """Only a plant that flowered long enough to seed adds to what its line hands on."""
    genome = genome_from_seed(TENDED_SEED)
    barren = grow(germinate(TENDED_SEED), genome, TENDED, 100)
    assert not has_seeded(barren)
    assert germinate_successor(barren).lineage_blooms == barren.lineage_blooms

    seeded = grow(germinate(TENDED_SEED), genome, TENDED, BLOOM_HEALTHY_STEPS + SEED_BLOOM_STEPS)
    assert has_seeded(seeded)
    heir = germinate_successor(seeded)
    assert heir.lineage_blooms == seeded.lineage_blooms + 1
    assert heir.stats == LifeStats(), "an heir inherits the record, never the life"


def test_serialize_round_trips_a_plant_with_an_epiphyte() -> None:
    """A whole plant survives storage: its life statistics and its passenger too."""
    from structure import deserialize

    genome = genome_from_seed(TENDED_SEED)
    plant = grow(_epiphyte_ready(), genome, TENDED, 30)
    assert plant.epiphyte is not None
    assert deserialize(serialize(plant)) == plant


# --- Regression: the active-tips cache must not change growth output --------


def _hash(plant) -> str:
    """A stable fingerprint of a structure's serialised form."""
    return hashlib.sha256(json.dumps(serialize(plant), sort_keys=True).encode()).hexdigest()


def test_growth_output_is_unchanged_by_the_active_tips_cache() -> None:
    """The active-tips bookkeeping is a pure perf cache: it must not alter output.

    ``_growth_step`` iterates ``Structure.active_tips`` instead of rescanning every
    node for ``NodeState.TIP`` each step, so a step's cost tracks the crown's active
    tip count rather than the accumulated body size. These hashes were captured
    from the prior full-scan implementation, for a small tree and a large/complex
    one (grown large, aged and flowered enough to carry an epiphyte, i.e. it also
    exercises dieback-adjacent bookkeeping and :func:`_advance_epiphyte`). Iterating
    only the active tips must still produce byte-for-byte identical structures.

    Recomputed once, for Phase 15's ``bloom_intensity`` field on
    :func:`serialize`'s output — a legitimate schema addition, not a topology
    change, so the hashes moved but the guarantee this test checks did not.
    """
    small = _grown(99, 0.85, 25)
    assert _hash(small) == "75ce399dcdc8fc6fbc3393c7f0ac97f68ba75ce60a73fc573811cddd38b1cac2"

    genome = genome_from_seed(TENDED_SEED)
    large = grow(_epiphyte_ready(), genome, TENDED, 100)
    assert large.epiphyte is not None, "the large fixture should have settled an epiphyte"
    assert _hash(large) == "08a8c2b9416b3f385b0420cf1d4bd2dadbbdeb2ea52e6d95df75ce3378ddf2fa"


# --- Phase 11: author breadth (crown branching) ------------------------------


def test_author_breadth_with_no_recent_voices_is_zero() -> None:
    assert author_breadth([]) == 0.0
    assert author_breadth([0.0, 0.0]) == 0.0


def test_author_breadth_ignores_authors_below_the_presence_floor() -> None:
    """A weight just short of the floor does not count as an active voice."""
    from structure import AUTHOR_PRESENCE_FLOOR

    assert author_breadth([AUTHOR_PRESENCE_FLOOR - 0.01] * 5) == 0.0


def test_author_breadth_counts_voices_at_or_above_the_floor() -> None:
    from structure import AUTHOR_PRESENCE_FLOOR

    weights = [AUTHOR_PRESENCE_FLOOR, AUTHOR_PRESENCE_FLOOR, 0.0, 0.05]
    assert author_breadth(weights) == 2 / BREADTH_SATURATION_VOICES


def test_author_breadth_saturates_at_the_configured_voice_count() -> None:
    at_saturation = author_breadth([1.0] * BREADTH_SATURATION_VOICES)
    beyond_saturation = author_breadth([1.0] * (BREADTH_SATURATION_VOICES + 10))
    assert at_saturation == 1.0
    assert beyond_saturation == 1.0


def test_grow_without_breadth_matches_the_explicit_neutral_value() -> None:
    """grow()'s default reproduces the exact pre-Phase-11 growth: neutral breadth."""
    structure = germinate(7)
    genome = genome_from_seed(7)
    without_breadth = grow(structure, genome, 0.9, 200)
    with_neutral_breadth = grow(structure, genome, 0.9, 200, 0.5)
    assert serialize(without_breadth) == serialize(with_neutral_breadth)


def test_higher_breadth_grows_a_wider_more_branched_crown() -> None:
    """Same seed, moisture and steps; only breadth differs.

    A many-voiced channel (breadth 1.0) should end up with a larger share of its
    body off the main axis (order >= 1) than a single-dominant-voice channel
    (breadth 0.0) — breadth only reshapes how bushy the crown is, checked here
    across several seeds so the effect isn't an artefact of one seed's draws.
    """
    for seed in (1, 2, 3, 42, 99, 123):
        structure = germinate(seed)
        genome = genome_from_seed(seed)
        narrow = grow(structure, genome, 0.9, 300, 0.0)
        wide = grow(structure, genome, 0.9, 300, 1.0)

        narrow_branch_share = sum(1 for n in narrow.nodes if n.order >= 1) / len(narrow.nodes)
        wide_branch_share = sum(1 for n in wide.nodes if n.order >= 1) / len(wide.nodes)

        assert wide_branch_share > narrow_branch_share, f"seed {seed}"


def test_breadth_does_not_change_the_genome_or_moisture_gate() -> None:
    """Breadth only touches branching: a fully parched plant still only diebacks,
    regardless of how many voices are active."""
    structure = germinate(5)
    genome = genome_from_seed(5)
    parched_narrow = grow(structure, genome, 0.0, 20, 0.0)
    parched_wide = grow(structure, genome, 0.0, 20, 1.0)
    assert serialize(parched_narrow) == serialize(parched_wide)


# --- Phase 12: temporal rhythm (growth shape / symmetry) ---------------------


def test_grow_without_rhythm_matches_the_explicit_neutral_value() -> None:
    """grow()'s default reproduces the exact pre-Phase-12 growth: neutral rhythm."""
    structure = germinate(7)
    genome = genome_from_seed(7)
    without_rhythm = grow(structure, genome, 0.9, 200)
    with_neutral_rhythm = grow(structure, genome, 0.9, 200, 0.5, 0.5)
    assert serialize(without_rhythm) == serialize(with_neutral_rhythm)


def test_lower_rhythm_grows_a_more_irregular_less_symmetric_body() -> None:
    """Same seed, moisture and steps; only rhythm differs.

    A bursty channel (rhythm 0.0) should end up with a larger average angular
    deviation from each limb's own bearing than a steady channel (rhythm 1.0)
    — rhythm only reshapes how gnarled the body looks, checked here across
    several seeds so the effect isn't an artefact of one seed's draws.
    """
    for seed in (1, 2, 3, 42, 99, 123):
        structure = germinate(seed)
        genome = genome_from_seed(seed)
        steady = grow(structure, genome, 0.9, 300, 0.5, 1.0)
        bursty = grow(structure, genome, 0.9, 300, 0.5, 0.0)

        assert _mean_angle_deviation(bursty) > _mean_angle_deviation(steady), f"seed {seed}"


def test_rhythm_does_not_change_the_genome_or_moisture_gate() -> None:
    """Rhythm only touches angle noise: a fully parched plant still only diebacks,
    regardless of how steady or bursty its activity was."""
    structure = germinate(5)
    genome = genome_from_seed(5)
    parched_steady = grow(structure, genome, 0.0, 20, 0.5, 1.0)
    parched_bursty = grow(structure, genome, 0.0, 20, 0.5, 0.0)
    assert serialize(parched_steady) == serialize(parched_bursty)


def test_rhythm_and_breadth_modifiers_do_not_interfere() -> None:
    """High breadth + bursty rhythm vs. low breadth + steady rhythm, and every
    combination in between: branching and angle noise stay legible and
    independent, not entangled by a shared random draw.

    Branch topology (which nodes exist, and each one's branch order) is exactly
    unaffected by rhythm at fixed breadth: ``random.uniform`` consumes exactly
    one draw from a tip's own independently-seeded RNG regardless of how wide a
    range it draws within, so scaling that range (what rhythm does) never shifts
    any later branch-or-not decision in the same stream.
    """
    seed = 77
    structure = germinate(seed)
    genome = genome_from_seed(seed)

    low_breadth_steady = grow(structure, genome, 0.9, 250, 0.0, 1.0)
    low_breadth_bursty = grow(structure, genome, 0.9, 250, 0.0, 0.0)
    high_breadth_steady = grow(structure, genome, 0.9, 250, 1.0, 1.0)
    high_breadth_bursty = grow(structure, genome, 0.9, 250, 1.0, 0.0)

    def topology(struct):
        return [(n.id, n.parent_id, n.order) for n in struct.nodes]

    # Exact: rhythm never changes which nodes exist or how they branch.
    assert topology(low_breadth_steady) == topology(low_breadth_bursty)
    assert topology(high_breadth_steady) == topology(high_breadth_bursty)

    # Breadth still drives branching as before, at either rhythm extreme.
    def branch_share(struct):
        return sum(1 for n in struct.nodes if n.order >= 1) / len(struct.nodes)

    assert branch_share(high_breadth_steady) > branch_share(low_breadth_steady)
    assert branch_share(high_breadth_bursty) > branch_share(low_breadth_bursty)

    # Rhythm still drives angle deviation as before, at either breadth extreme.
    assert _mean_angle_deviation(low_breadth_bursty) > _mean_angle_deviation(low_breadth_steady)
    assert _mean_angle_deviation(high_breadth_bursty) > _mean_angle_deviation(high_breadth_steady)

    # And breadth's crosstalk into angle deviation is small next to rhythm's own
    # swing: changing breadth alone should move this metric far less than
    # changing rhythm alone does.
    rhythm_swing = _mean_angle_deviation(low_breadth_bursty) - _mean_angle_deviation(low_breadth_steady)
    breadth_crosstalk = abs(
        _mean_angle_deviation(high_breadth_steady) - _mean_angle_deviation(low_breadth_steady)
    )
    assert breadth_crosstalk < rhythm_swing
