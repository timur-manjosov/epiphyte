"""Pure body logic for Epiphyte: the plant's accumulating body and its scars.

No side effects, no clock reads, no ``import discord`` and no Pillow. Given the
same inputs these functions always return the same outputs, which makes them
testable with pytest without drawing anything or starting Discord.

This module replaces the old "moisture -> L-system depth -> fixed shape" model.
A plant is no longer a function of its current moisture: it is the accumulated
result of its whole life. Growth is applied in discrete steps, each step advances
every living tip a little, and what has grown stays part of the body.

Vitality and body are decoupled. When moisture is healthy the plant grows; when
it is parched the plant dies back from the outside in, turning living wood into
dead wood. Dead wood is never removed and never revives, so a drought is written
permanently into the body — a scar still legible long after the plant recovers.

A drought that never lifts reaches the base and kills the whole plant: once every
node is dead the plant is dead. From that death a successor germinates — a
single-gene mutation of the parent's seed, so it resembles the parent yet is its
own individual — carrying the lineage (generation and parent seed) forward. There
is no final state; the line simply continues.

Two plants with the same ``seed`` are identical (same :class:`Genome`, same
growth) — that seeded determinism *is* each plant's individuality. Growth is
also chunk-invariant: running ``steps`` steps at once yields exactly the same
structure as running the same steps one at a time, because every decision is
seeded by ``(seed, node_id, step_index)`` and never by call boundaries.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from enum import Enum

# --- Growth constants (rules, not user configuration) ------------------------
#
# The dynamics are deliberately self-limiting. Below its carrying capacity a
# plant only grows — tips extend and branch, and nothing is ever removed, so it
# can never go extinct and freeze. Above capacity, extending tips cap off under a
# termination pressure that keeps the crown near capacity while it keeps turning
# over — old tips finish, new ones branch out — so branches stay finite and the
# crown stays bushy rather than growing into a bundle of endless parallel whips.
# Moisture sets the *pace* of growth; the genome's vigour sets how big the crown
# gets. Growth can neither explode nor die out; it accumulates, faster when wet.

#: Fraction of full moisture that becomes a tip's per-step chance to extend. Even
#: a soaked plant grows at a measured pace, so a big tree takes weeks of health.
EXTENSION_RATE: float = 0.5
#: Baseline crown carrying capacity (active tips) at vigour ``1.0``; scaled by the
#: genome's vigour so some plants stay sparse and others grow dense.
BASE_CAPACITY: float = 12.0
#: Floor on carrying capacity, so even a low-vigour plant can branch a little.
MIN_CAPACITY: int = 4
#: How hard the crown is trimmed once over capacity: an extending tip's chance to
#: cap off is this times the fractional overshoot (bounded by MAX_TERMINATION).
OVERCAPACITY_PRESSURE: float = 1.5
#: Ceiling on that per-tip termination chance, so an overshoot is trimmed back
#: gradually over several steps rather than the whole crown capping off at once.
MAX_TERMINATION: float = 0.6
#: Branch generations beyond which tips only extend, never fork. Bounds depth.
MAX_ORDER: int = 6
#: Per-order decay of the branching chance (apical dominance): higher-order side
#: branches split far less often than the main axis, giving the natural "few big
#: branches, many fine twigs" look.
BRANCH_ORDER_DECAY: float = 0.5
#: Per-order shortening of internodes: twigs are shorter than the trunk.
LENGTH_ORDER_DECAY: float = 0.9
#: Fractional random spread applied to each internode's length (organic noise).
LENGTH_JITTER: float = 0.15
#: The direction the growing tip is gently pulled toward, in degrees (straight up).
UPRIGHT_ANGLE: float = 90.0

# --- Dieback constants (the body remembers drought) --------------------------
#
# Vitality (moisture) and body are decoupled. Above the threshold the plant lives
# and grows; below it the plant is parched and dies back from the outside in.
# Dead wood is never removed and never revives, so a drought leaves a permanent
# scar in the body that stays legible long after the plant has recovered.

#: Vitality below which the plant stops growing and begins to die back. Set deep
#: inside the withered band, so only a real, sustained drought kills wood.
DIEBACK_MOISTURE_THRESHOLD: float = 0.08
#: Chance an exposed living end dies in one step at zero vitality.
DIEBACK_MAX_RATE: float = 0.5
#: Steepness of the dieback curve in the drought's severity. High, so a moderate
#: drought only nibbles the outer crown (Phase 7's partial scars, with survivors),
#: while a lasting silence that drives vitality to zero collapses the whole plant
#: at pace — the difference between a bad week and abandonment.
DIEBACK_EXPONENT: float = 2.5


class NodeState(Enum):
    """A node's vitality: growing tip, living wood, or dead wood (a scar)."""

    TIP = "tip"
    WOODY = "woody"
    DEAD = "dead"


@dataclass(frozen=True)
class Node:
    """A single point in the plant's body, in the plant's own coordinate space.

    ``+y`` points up. ``angle`` is the growth heading in degrees (measured
    counter-clockwise from ``+x``, so ``90`` is straight up). ``order`` is the
    branching generation (``0`` on the main axis). ``birth_step`` records the
    growth step the node was created in. Node ids are assigned sequentially, so a
    node's id equals its index in :attr:`Structure.nodes` and every child's
    ``parent_id`` is strictly less than its own id. Thickness is *not* stored per
    node — the renderer derives it from how many tips a node carries (pipe model).
    """

    id: int
    parent_id: int | None
    x: float
    y: float
    angle: float
    birth_step: int
    order: int
    state: NodeState


@dataclass(frozen=True)
class Structure:
    """A plant body: its nodes as a tree, its ``seed``, age and lineage.

    ``nodes`` is ordered by id (``nodes[i].id == i``); ``nodes[0]`` is the germ.
    ``step_count`` is how many growth steps have been applied so far, and doubles
    as the index of the next step to run. ``generation`` is ``1`` for a founding
    plant and rises with each successor; ``parent_seed`` is the seed of the
    predecessor this plant sprang from (``None`` for a founder), so the body
    carries its own lineage.
    """

    nodes: tuple[Node, ...]
    step_count: int
    seed: int
    generation: int = 1
    parent_seed: int | None = None


@dataclass(frozen=True)
class Genome:
    """The heritable shape parameters of a plant, derived from its seed.

    Same seed ⇒ same genome ⇒ same plant. The genes shape *how* the body grows,
    while the per-node seeded randomness decides *what* each individual tip does.
    """

    #: Mean angle (degrees) a side branch diverges from its parent's heading.
    branch_angle: float
    #: Spread (degrees) of the organic angle noise on every new internode.
    angle_jitter: float
    #: Base chance an active tip branches (before per-order decay).
    branch_probability: float
    #: Base internode length in plant-space units.
    internode_length: float
    #: Strength (0..1) of the pull back toward vertical on each new internode.
    gravitropism: float
    #: Growth vigour: scales how readily tips act at a given moisture.
    vigor: float
    #: Leaf size multiplier — how large this plant's individual leaves render.
    leaf_size: float
    #: Leaf density multiplier — how thickly living tips are foliaged.
    leaf_density: float


# --- Heredity: genes packed into the seed's bit-fields -------------------------
#
# Each gene is an independent bit-field of the seed, scaled into its range below.
# Because the genes are independent, a mutation can re-roll a single trait while
# the child inherits all the others — so a descendant clearly resembles its parent
# yet is its own individual, and a lineage drifts one trait at a time.
_GENE_BITS = 7
_GENE_MAX = (1 << _GENE_BITS) - 1  # 127 levels per gene
_GENE_COUNT = 8                    # eight genes -> 56 of the seed's bits


def _allele(seed: int, index: int) -> float:
    """Read gene ``index`` from the seed's bit-field as a value in ``[0, 1]``."""
    return ((seed >> (index * _GENE_BITS)) & _GENE_MAX) / _GENE_MAX


def _scaled(low: float, high: float, allele: float) -> float:
    """Scale a ``[0, 1]`` allele into the gene's ``[low, high]`` range."""
    return low + allele * (high - low)


def genome_from_seed(seed: int) -> Genome:
    """Derive a plant's :class:`Genome` deterministically from an integer seed.

    Each gene reads an independent bit-field of the seed, so two seeds differing in
    one field share every other trait — which is what lets :func:`mutate` breed a
    recognisable but distinct descendant.
    """
    return Genome(
        branch_angle=_scaled(26.0, 50.0, _allele(seed, 0)),
        angle_jitter=_scaled(4.0, 9.0, _allele(seed, 1)),
        branch_probability=_scaled(0.18, 0.34, _allele(seed, 2)),
        internode_length=_scaled(8.0, 13.0, _allele(seed, 3)),
        gravitropism=_scaled(0.04, 0.12, _allele(seed, 4)),
        vigor=_scaled(0.8, 1.3, _allele(seed, 5)),
        leaf_size=_scaled(0.8, 1.4, _allele(seed, 6)),
        leaf_density=_scaled(0.7, 1.5, _allele(seed, 7)),
    )


def mutate(seed: int) -> int:
    """Return a deterministic single-gene mutation of ``seed``.

    Exactly one gene's bit-field is re-rolled to a different value while every
    other gene is inherited unchanged, so the result is always different from
    ``seed`` yet a close relative of it. Pure and deterministic.
    """
    rng = random.Random(f"epiphyte-mutate:{seed}")
    shift = rng.randrange(_GENE_COUNT) * _GENE_BITS
    allele = (seed >> shift) & _GENE_MAX
    changed = allele ^ rng.randint(1, _GENE_MAX)  # nonzero xor -> guaranteed change
    return (seed & ~(_GENE_MAX << shift)) | (changed << shift)


def germinate(seed: int, generation: int = 1, parent_seed: int | None = None) -> Structure:
    """Return a fresh structure: a single germ tip at the origin, growing up.

    ``generation`` and ``parent_seed`` carry the lineage; a founding plant leaves
    them at their defaults (generation 1, no parent).
    """
    germ = Node(
        id=0,
        parent_id=None,
        x=0.0,
        y=0.0,
        angle=UPRIGHT_ANGLE,
        birth_step=0,
        order=0,
        state=NodeState.TIP,
    )
    return Structure(
        nodes=(germ,), step_count=0, seed=seed, generation=generation, parent_seed=parent_seed
    )


def is_dead(structure: Structure) -> bool:
    """True if every node is dead — the whole plant, inner wood and all, has died."""
    return all(node.state is NodeState.DEAD for node in structure.nodes)


def germinate_successor(structure: Structure) -> Structure:
    """Germinate a dead plant's successor: a mutated seed, the next generation.

    The successor's seed is a single-gene :func:`mutate` of the parent's, so it
    resembles the parent but is its own individual; ``generation`` rises by one and
    the parent's seed is recorded as lineage. Pure — the caller (the adapter)
    decides *when* a dead plant reseeds.
    """
    return germinate(
        mutate(structure.seed),
        generation=structure.generation + 1,
        parent_seed=structure.seed,
    )


def _clamp01(value: float) -> float:
    """Clamp ``value`` into ``[0.0, 1.0]``."""
    return max(0.0, min(1.0, value))


def _nudged_angle(base_angle: float, genome: Genome, rng: random.Random) -> float:
    """Pull ``base_angle`` toward vertical by the genome's gravitropism, then add
    one organic jitter draw. Consumes exactly one random number."""
    toward_up = base_angle + genome.gravitropism * (UPRIGHT_ANGLE - base_angle)
    return toward_up + rng.uniform(-genome.angle_jitter, genome.angle_jitter)


def _child(
    parent: Node, angle: float, length: float, step_index: int, order: int, node_id: int
) -> Node:
    """Create a new tip node one internode away from ``parent`` along ``angle``."""
    radians = math.radians(angle)
    return Node(
        id=node_id,
        parent_id=parent.id,
        x=parent.x + length * math.cos(radians),
        y=parent.y + length * math.sin(radians),
        angle=angle,
        birth_step=step_index,
        order=order,
        state=NodeState.TIP,
    )


def _capacity(genome: Genome) -> int:
    """Crown carrying capacity (max active tips) for a genome, from its vigour."""
    return max(MIN_CAPACITY, round(BASE_CAPACITY * genome.vigor))


def _grow_tip(
    tip: Node,
    nodes: list[Node],
    genome: Genome,
    step_index: int,
    terminate_chance: float,
    rng: random.Random,
) -> None:
    """Advance one active tip by one step, mutating the working ``nodes`` list.

    The tip always lignifies. With probability ``terminate_chance`` (only nonzero
    once the crown is over capacity) it caps off there — no continuation — trimming
    the crown. Otherwise it puts out a continuation on the same axis and, with a
    probability that decays with branch order, a diverging side branch. New node
    ids continue the sequence, preserving the ``id == index`` invariant.
    """
    nodes[tip.id] = replace(tip, state=NodeState.WOODY)
    if rng.random() < terminate_chance:
        return  # capped off: this branch has a finished, lignified end

    base_length = genome.internode_length * (LENGTH_ORDER_DECAY ** tip.order)

    def internode() -> float:
        return base_length * (1.0 + rng.uniform(-LENGTH_JITTER, LENGTH_JITTER))

    continuation_angle = _nudged_angle(tip.angle, genome, rng)
    nodes.append(_child(tip, continuation_angle, internode(), step_index, tip.order, len(nodes)))

    branch_chance = genome.branch_probability * (BRANCH_ORDER_DECAY ** tip.order)
    if tip.order < MAX_ORDER and rng.random() < branch_chance:
        side = 1.0 if rng.random() < 0.5 else -1.0
        lateral_angle = _nudged_angle(tip.angle + side * genome.branch_angle, genome, rng)
        nodes.append(
            _child(tip, lateral_angle, internode(), step_index, tip.order + 1, len(nodes))
        )


def _children_map(nodes: list[Node]) -> dict[int, list[int]]:
    """Map each node id to the ids of its children (empty for a leaf/tip)."""
    children: dict[int, list[int]] = {}
    for node in nodes:
        if node.parent_id is not None:
            children.setdefault(node.parent_id, []).append(node.id)
    return children


def _living_frontier(nodes: list[Node], children: dict[int, list[int]]) -> list[Node]:
    """Return the living nodes at the outer edge of living tissue.

    A node is on the frontier if it is alive (``TIP`` or ``WOODY``) and every one
    of its children is already ``DEAD`` — a tip, having no children, always
    qualifies. Recomputed each dieback step, this frontier marches inward: the
    outermost tips die first, then the wood they fed becomes exposed and dies next.
    """
    frontier: list[Node] = []
    for node in nodes:
        if node.state is NodeState.DEAD:
            continue
        kids = children.get(node.id, ())
        if all(nodes[k].state is NodeState.DEAD for k in kids):
            frontier.append(node)
    return frontier


def _growth_step(
    nodes: list[Node],
    genome: Genome,
    seed: int,
    extension_chance: float,
    capacity: int,
    step_index: int,
) -> None:
    """Apply one growth step: living tips may extend, branch, or cap off."""
    tips = [node for node in nodes if node.state is NodeState.TIP]
    # The termination pressure is sampled once per step from the crown size at its
    # start, so it does not depend on the order tips are visited within the step,
    # and it is zero until the crown exceeds capacity.
    overshoot = max(0, len(tips) - capacity) / capacity
    terminate_chance = min(MAX_TERMINATION, OVERCAPACITY_PRESSURE * overshoot)
    for tip in tips:
        rng = random.Random(f"{seed}:{tip.id}:{step_index}")
        if rng.random() >= extension_chance:
            continue  # dormant this step; may grow in a later one
        _grow_tip(tip, nodes, genome, step_index, terminate_chance, rng)


def _dieback_step(nodes: list[Node], seed: int, vitality: float, step_index: int) -> None:
    """Apply one dieback step: the exposed living frontier may die (turn ``DEAD``).

    The chance each exposed end dies scales with how far vitality has fallen below
    :data:`DIEBACK_MOISTURE_THRESHOLD`, so a deeper, longer drought kills more and
    reaches further in. Dead wood is never removed and never revives — it stays a
    scar — so a drought is permanently legible in the body. A drought that never
    lifts reaches the very base and kills the whole plant (see :func:`is_dead`);
    only a germ that has *never grown* is spared, lying dormant as a seed rather
    than dying, so an unwatered fresh sprout waits for water instead of dying on
    the spot.
    """
    severity = _clamp01((DIEBACK_MOISTURE_THRESHOLD - vitality) / DIEBACK_MOISTURE_THRESHOLD)
    death_chance = DIEBACK_MAX_RATE * severity ** DIEBACK_EXPONENT
    if death_chance <= 0.0:
        return
    children = _children_map(nodes)
    for node in _living_frontier(nodes, children):
        if node.id == 0 and not children.get(0):
            continue  # a germ that never grew is a dormant seed, not a dying plant
        rng = random.Random(f"dieback:{seed}:{node.id}:{step_index}")
        if rng.random() < death_chance:
            nodes[node.id] = replace(node, state=NodeState.DEAD)


def grow(structure: Structure, genome: Genome, moisture: float, steps: int) -> Structure:
    """Return the structure advanced ``steps`` life-steps under ``moisture`` (pure).

    Each step runs one of two regimes, chosen by the vitality that ``moisture``
    gates:

    * **Growth** (vitality at or above :data:`DIEBACK_MOISTURE_THRESHOLD`): every
      living tip may extend, branch, or cap off. The chance a tip extends scales
      with moisture — brisk when wet, almost nothing when barely healthy — and the
      crown self-limits at its carrying capacity. This is the honest signal.
    * **Dieback** (vitality below the threshold): the plant is parched, so instead
      of growing it dies back from the outside in. Dead wood stays in the body
      forever, a permanent scar of the drought.

    So the number of dead nodes only ever rises, and lignified wood (living plus
    dead) never falls: the body accumulates monotonically and remembers its whole
    life. Decisions are seeded by ``(seed, node_id, step_index)``, so this is
    deterministic and chunk-invariant — the same total steps produce the same
    result whether run at once or one at a time. The input is never mutated.
    """
    vitality = _clamp01(moisture)
    extension_chance = vitality * EXTENSION_RATE
    capacity = _capacity(genome)
    nodes = list(structure.nodes)
    step_index = structure.step_count

    for _ in range(max(0, steps)):
        if vitality < DIEBACK_MOISTURE_THRESHOLD:
            _dieback_step(nodes, structure.seed, vitality, step_index)
        else:
            _growth_step(nodes, genome, structure.seed, extension_chance, capacity, step_index)
        step_index += 1

    return Structure(
        nodes=tuple(nodes),
        step_count=step_index,
        seed=structure.seed,
        generation=structure.generation,
        parent_seed=structure.parent_seed,
    )


def serialize(structure: Structure) -> dict:
    """Return a JSON-serialisable dict fully describing ``structure`` (pure)."""
    return {
        "seed": structure.seed,
        "step_count": structure.step_count,
        "generation": structure.generation,
        "parent_seed": structure.parent_seed,
        "nodes": [
            {
                "id": node.id,
                "parent_id": node.parent_id,
                "x": node.x,
                "y": node.y,
                "angle": node.angle,
                "birth_step": node.birth_step,
                "order": node.order,
                "state": node.state.value,
            }
            for node in structure.nodes
        ],
    }


def deserialize(data: dict) -> Structure:
    """Rebuild a :class:`Structure` from :func:`serialize`'s output (pure)."""
    nodes = tuple(
        Node(
            id=entry["id"],
            parent_id=entry["parent_id"],
            x=entry["x"],
            y=entry["y"],
            angle=entry["angle"],
            birth_step=entry["birth_step"],
            order=entry["order"],
            state=NodeState(entry["state"]),
        )
        for entry in data["nodes"]
    )
    return Structure(
        nodes=nodes,
        step_count=data["step_count"],
        seed=data["seed"],
        generation=data.get("generation", 1),
        parent_seed=data.get("parent_seed"),
    )
