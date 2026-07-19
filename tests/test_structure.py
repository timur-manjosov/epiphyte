"""Tests for the pure growth logic. No Pillow, no Discord, no persistence.

These cover the properties Phase 5 promises: germination, seeded determinism and
individuality, additive growth, moisture-scaled growth, and a consistent tree
topology.
"""

from structure import (
    NodeState,
    genome_from_seed,
    germinate,
    grow,
    serialize,
)


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
