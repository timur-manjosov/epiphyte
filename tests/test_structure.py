"""Tests for the pure body logic. No Pillow, no Discord, no persistence.

Phase 5 properties: germination, seeded determinism and individuality, additive
growth, moisture-scaled growth, and a consistent tree topology. Phase 7 adds the
biography: drought kills wood from the outside in, dead wood is a permanent scar
that survives recovery, and the accumulated body never shrinks.
"""

from structure import (
    NodeState,
    genome_from_seed,
    germinate,
    grow,
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

#: A moisture deep below the dieback threshold — a real, killing drought.
DROUGHT = 0.02


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
    seed = 35
    genome = genome_from_seed(seed)
    withered = grow(_grown(seed, 0.7, 60), genome, DROUGHT, 12)

    assert _count_state(withered, NodeState.DEAD) > 0, "some wood should have died"
    assert _count_state(withered, NodeState.TIP) > 0, "some tips should survive"

    recovered = grow(withered, genome, 0.9, 40)
    assert len(recovered.nodes) > len(withered.nodes)  # new growth returns
