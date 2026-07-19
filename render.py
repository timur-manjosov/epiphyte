"""Rendering for Epiphyte: turn a plant structure into a PNG (Pillow I/O).

This module only draws. It performs no growth or dieback computation — it receives
an already-grown :class:`structure.Structure`, the plant's current vitality
(moisture) and its :class:`structure.Genome`, and paints them in the Nord colour
scheme. Kept separate so the pure logic stays free of any Pillow dependency.

The *body* is fixed — the stems and their thickness come straight from the
structure — while the *vitality* modulates the look over that body: living tips
carry leaves whose size and number scale with moisture and the genome, colours
run from lush teal-green when wet to a parched, desaturated brown when dry, and
the young ends droop under drought. Dead wood is always drawn bare and weathered
grey, so a healed drought's scar stays visible however lush the rest becomes.

Stem thickness follows the pipe model: a node's width is derived from how many
tips (terminal endpoints) its subtree carries, so the trunk that feeds the whole
crown is thick and the fine twigs are thin. Colour runs along height, from rooted
brown at the base to living teal at the top.
"""

from __future__ import annotations

import io
import math
import random

from PIL import Image, ImageDraw

from structure import Genome, Node, NodeState, Structure

# Nord palette (RGB), matching the table in CLAUDE.md.
BACKGROUND = (46, 52, 64)    # #2E3440
EARTH = (59, 66, 82)         # #3B4252
STEM_BOTTOM = (94, 74, 59)   # #5E4A3B rooted brown
STEM_TOP = (143, 188, 187)   # #8FBCBB living teal
LEAF = (163, 190, 140)       # #A3BE8C
ACCENT = (136, 192, 208)     # #88C0D0 bud

#: Bleached driftwood grey of dead wood — constant, unaffected by vitality (a
#: scar). Light and desaturated, so it reads as dead against the cool living teal.
DEAD_WOOD = (150, 144, 134)
#: Parched target that living tissue is tinted toward as vitality falls.
PARCHED = (120, 104, 82)
#: How far toward PARCHED fully-dry living tissue is tinted (0..1).
PARCH_STRENGTH = 0.72

#: Final image size in pixels.
WIDTH = 480
HEIGHT = 600
#: Draw at this multiple of the final size, then shrink for cheap anti-aliasing.
SUPERSAMPLE = 2

_W = WIDTH * SUPERSAMPLE
_H = HEIGHT * SUPERSAMPLE
_PADDING = 48 * SUPERSAMPLE
_EARTH_HEIGHT = 90 * SUPERSAMPLE
_ROOT_OVERLAP = 8 * SUPERSAMPLE  # how far the stem base sinks into the earth

#: Thinnest and thickest stem widths, in supersampled pixels.
_MIN_STEM = 1.4 * SUPERSAMPLE
_MAX_STEM = 13.0 * SUPERSAMPLE

#: Maximum downward sag of the young ends under full drought (supersampled px).
_DROOP_MAX = 58.0 * SUPERSAMPLE
#: Base leaf radius (supersampled px) and how many leaves a full, dense tip grows.
_LEAF_RADIUS = 4.6 * SUPERSAMPLE
_LEAF_CLUSTER_MAX = 7

Color = tuple[int, int, int]


def _lerp_color(low: Color, high: Color, t: float) -> Color:
    """Linearly interpolate between two RGB colours; ``t`` is clamped to [0, 1]."""
    t = max(0.0, min(1.0, t))
    return tuple(round(a + (b - a) * t) for a, b in zip(low, high))  # type: ignore[return-value]


def _parch(color: Color, vitality: float) -> Color:
    """Tint a living colour toward the parched brown as vitality falls."""
    dryness = 1.0 - max(0.0, min(1.0, vitality))
    return _lerp_color(color, PARCHED, dryness * PARCH_STRENGTH)


def render(structure: Structure, moisture: float, genome: Genome) -> io.BytesIO:
    """Render a plant to a PNG and return it as a ``BytesIO``.

    ``moisture`` is the plant's current vitality (0..1) and ``genome`` its
    heritable look; together they modulate foliage, colour and posture over the
    fixed body. Draws the Nord background and earth band, then the plant, centred
    and scaled to fit. A just-germinated plant (a single node) is drawn as a
    sprout. The returned buffer is rewound to the start.
    """
    vitality = max(0.0, min(1.0, moisture))
    image = Image.new("RGB", (_W, _H), BACKGROUND)
    draw = ImageDraw.Draw(image)

    earth_top = _H - _EARTH_HEIGHT
    draw.rectangle((0, earth_top, _W, _H), fill=EARTH)

    if len(structure.nodes) > 1:
        _draw_structure(draw, structure, genome, vitality, earth_top)
    else:
        _draw_sprout(draw, vitality, genome, earth_top)

    image = image.resize((WIDTH, HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _draw_sprout(draw: ImageDraw.ImageDraw, vitality: float, genome: Genome, earth_top: int) -> None:
    """Draw a tiny fresh sprout for a just-germinated, single-node plant."""
    base_x = _W / 2
    root_y = earth_top + _ROOT_OVERLAP
    tip_y = root_y - 22 * SUPERSAMPLE
    draw.line((base_x, root_y, base_x, tip_y), fill=_parch(STEM_TOP, vitality), width=round(_MIN_STEM * 2))
    if vitality > 0.1:
        _draw_leaves(draw, (base_x, tip_y), vitality, genome, node_id=0)
    else:
        radius = 4 * SUPERSAMPLE
        draw.ellipse((base_x - radius, tip_y - radius, base_x + radius, tip_y + radius), fill=ACCENT)


def _subtree_tip_counts(structure: Structure) -> dict[int, int]:
    """Return, per node id, how many terminal endpoints its subtree carries.

    Leaves (nodes without children) count as one; the count sums up the tree.
    Because a child's id always exceeds its parent's, iterating ids high-to-low
    processes every child before its parent.
    """
    children: dict[int, list[int]] = {}
    for node in structure.nodes:
        if node.parent_id is not None:
            children.setdefault(node.parent_id, []).append(node.id)

    counts: dict[int, int] = {}
    for node in sorted(structure.nodes, key=lambda n: n.id, reverse=True):
        kids = children.get(node.id)
        counts[node.id] = 1 if not kids else sum(counts[k] for k in kids)
    return counts


def _draw_leaves(
    draw: ImageDraw.ImageDraw,
    tip_px: tuple[float, float],
    vitality: float,
    genome: Genome,
    node_id: int,
) -> None:
    """Draw a leaf cluster at a living tip; size and count scale with vitality.

    Placement is seeded by ``node_id`` so a tip's leaves stay put between renders
    instead of jittering every tick. As vitality falls the count drops to zero —
    the leaves fall — and the colour parches; on recovery they return.
    """
    count = round(genome.leaf_density * _LEAF_CLUSTER_MAX * vitality ** 1.2)
    if count <= 0:
        return
    rng = random.Random(f"leaf:{node_id}")
    base_r = _LEAF_RADIUS * genome.leaf_size * (0.55 + 0.45 * vitality)
    color = _parch(LEAF, vitality)
    cx, cy = tip_px
    for _ in range(count):
        angle = rng.uniform(0.0, 2.0 * math.pi)
        dist = rng.uniform(0.0, base_r * 1.5)
        lx = cx + dist * math.cos(angle)
        ly = cy + dist * math.sin(angle)
        r = base_r * rng.uniform(0.7, 1.1)
        draw.ellipse((lx - r, ly - r, lx + r, ly + r), fill=color)


def _draw_structure(
    draw: ImageDraw.ImageDraw,
    structure: Structure,
    genome: Genome,
    vitality: float,
    earth_top: int,
) -> None:
    """Draw the body (stems, pipe-model width, dead scars) and living foliage."""
    nodes = structure.nodes
    tip_counts = _subtree_tip_counts(structure)
    max_tips = max(tip_counts.values())
    dryness = 1.0 - vitality

    xs = [node.x for node in nodes]
    ys = [node.y for node in nodes]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    data_w = max_x - min_x
    data_h = max_y - min_y

    root_y = earth_top + _ROOT_OVERLAP
    area_w = _W - 2 * _PADDING
    area_h = root_y - _PADDING
    scale_x = area_w / data_w if data_w > 1e-9 else float("inf")
    scale_y = area_h / data_h if data_h > 1e-9 else float("inf")
    scale = min(scale_x, scale_y)
    if scale == float("inf"):
        scale = 1.0
    center_x = (min_x + max_x) / 2.0

    def height_fraction(y: float) -> float:
        return (y - min_y) / data_h if data_h > 1e-9 else 1.0

    def to_px(node: Node) -> tuple[float, float]:
        # Centre horizontally, root the base on the earth line, flip y so the plant
        # grows upward, then sag the young (high) ends downward when parched.
        droop = _DROOP_MAX * dryness * height_fraction(node.y) ** 1.25
        return (
            _W / 2 + (node.x - center_x) * scale,
            root_y - (node.y - min_y) * scale + droop,
        )

    def width_for(node_id: int) -> float:
        frac = (tip_counts[node_id] ** 0.5) / (max_tips ** 0.5)
        return max(_MIN_STEM, _MIN_STEM + (_MAX_STEM - _MIN_STEM) * frac)

    pixels = {node.id: to_px(node) for node in nodes}

    # Stems: draw thickest (trunk) first so the fine twigs sit cleanly on top. Dead
    # wood is a constant weathered grey; living wood is the height gradient, parched
    # toward brown as vitality falls.
    ordered = sorted(
        (node for node in nodes if node.parent_id is not None),
        key=lambda n: tip_counts[n.id],
        reverse=True,
    )
    for node in ordered:
        parent_px = pixels[node.parent_id]  # type: ignore[index]
        node_px = pixels[node.id]
        if node.state is NodeState.DEAD:
            color = DEAD_WOOD
        else:
            t = height_fraction((node.y + nodes[node.parent_id].y) / 2.0)  # type: ignore[index]
            color = _parch(_lerp_color(STEM_BOTTOM, STEM_TOP, t), vitality)
        width = width_for(node.id)
        draw.line((parent_px, node_px), fill=color, width=max(1, round(width)))
        # A dot at the joint rounds the corner where segments of unequal width meet.
        radius = width / 2.0
        cx, cy = node_px
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)

    # Foliage: leaves only on living tips, over the stems.
    for node in nodes:
        if node.state is NodeState.TIP:
            _draw_leaves(draw, pixels[node.id], vitality, genome, node.id)
