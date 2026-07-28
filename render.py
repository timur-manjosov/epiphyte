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

On top of that come the rare states a plant has to earn. In bloom it carries
blossoms in the colour its own genome flowers in; once it has set seed its tips
keep pale seed heads, which survive the drought that takes the blossoms; and a
tree old enough to have taken on an epiphyte carries that second little plant,
drawn as the independent structure it is, on the limb it settled on.

A bloom's own ``structure.stats.bloom_intensity`` (see ``structure.py``, Phase
15) additionally scales how abundant and how saturated its blossoms are: at
full intensity every living tip flowers at full colour, same as before Phase
15; at the floor only a sparse handful do, pale and washed toward white. This
module never computes that value — it only reads the number the already-grown
structure already carries, same as it reads ``is_blooming`` or ``has_seeded``.

Stem thickness follows the pipe model: a node's width is derived from how many
tips (terminal endpoints) its subtree carries, so the trunk that feeds the whole
crown is thick and the fine twigs are thin. Colour runs along height, from rooted
brown at the base to living teal at the top.
"""

from __future__ import annotations

import io
import math
import random
from collections.abc import Callable

from PIL import Image, ImageDraw

from structure import (
    Genome,
    NodeState,
    Structure,
    epiphyte_genome,
    has_seeded,
    is_blooming,
)

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

#: Nord accents the blossom colour is drawn from — the plant's bloom gene picks a
#: point along this ramp, so each individual flowers in a shade of its own. Ordered
#: frost → purple → red → orange → yellow, which keeps every blend on the palette.
BLOOM_RAMP: tuple[tuple[int, int, int], ...] = (
    (136, 192, 208),  # #88C0D0
    (180, 142, 173),  # #B48EAD
    (191, 97, 106),   # #BF616A
    (208, 135, 112),  # #D08770
    (235, 203, 139),  # #EBCB8B
)
#: Pale Nord snow of a seed head, and the brightness a blossom's eye is lifted to.
SEED_HEAD = (216, 222, 233)  # #D8DEE9
BLOSSOM_EYE = (236, 239, 244)  # #ECEFF4
#: Foliage of an epiphyte: the Nord frost accent. A second organism gets a colour of
#: its own, cooler and brighter than both the host's leaves and its stems, so it
#: reads as another species rather than as more of its host's crown.
EPIPHYTE_LEAF = ACCENT

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
#: Base radius of a blossom's petals and of a single seed in a seed head.
_BLOSSOM_RADIUS = 3.4 * SUPERSAMPLE
_SEED_RADIUS = 1.7 * SUPERSAMPLE
#: Petals per blossom, and seeds per seed head.
_PETALS = 5
_SEEDS_PER_HEAD = 3
#: Thickest stem of an epiphyte: it is a passenger, never a second trunk.
_EPIPHYTE_MAX_STEM = 3.0 * SUPERSAMPLE

Color = tuple[int, int, int]
#: One drawable stem: start and end in pixels, its colour and its width.
Segment = tuple[tuple[float, float], tuple[float, float], Color, float]


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
    leaf_color: Color = LEAF,
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
    color = _parch(leaf_color, vitality)
    cx, cy = tip_px
    for _ in range(count):
        angle = rng.uniform(0.0, 2.0 * math.pi)
        dist = rng.uniform(0.0, base_r * 1.5)
        lx = cx + dist * math.cos(angle)
        ly = cy + dist * math.sin(angle)
        r = base_r * rng.uniform(0.7, 1.1)
        draw.ellipse((lx - r, ly - r, lx + r, ly + r), fill=color)


def _bloom_color(genome: Genome) -> Color:
    """The blossom colour this genome flowers in: a point along :data:`BLOOM_RAMP`."""
    position = max(0.0, min(1.0, genome.bloom_hue)) * (len(BLOOM_RAMP) - 1)
    stop = min(int(position), len(BLOOM_RAMP) - 2)
    return _lerp_color(BLOOM_RAMP[stop], BLOOM_RAMP[stop + 1], position - stop)


#: Floor on a blossom's radius scale at the lowest bloom intensity, so a modest
#: bloom's flowers are smaller but never vanishingly tiny.
_INTENSITY_RADIUS_FLOOR: float = 0.6


def _draw_blossom(
    draw: ImageDraw.ImageDraw,
    tip_px: tuple[float, float],
    genome: Genome,
    node_id: int,
    color: Color,
    intensity: float = 1.0,
) -> None:
    """Draw one blossom at a living tip: a rosette of petals around a bright eye.

    The rosette's rotation is seeded by ``node_id`` so a flower keeps its face
    between renders instead of spinning every tick. ``intensity`` (see
    ``structure.LifeStats.bloom_intensity``) is spent on the same ``node_id``-seeded
    draw used for the rotation, before it: at ``1.0`` every tip flowers, same as
    before Phase 15 introduced this parameter; below that, only a fraction of tips
    do, chosen once per tip and stable between renders like everything else seeded
    by ``node_id``, and every blossom that does appear draws a little smaller —
    abundance and size, not hue, is how a modest bloom reads as modest.
    """
    rng = random.Random(f"bloom:{node_id}")
    if rng.random() >= intensity:
        return  # this tip's draw did not clear the bloom's abundance this life
    radius = _BLOSSOM_RADIUS * genome.leaf_size * (
        _INTENSITY_RADIUS_FLOOR + (1.0 - _INTENSITY_RADIUS_FLOOR) * intensity
    )
    phase = rng.uniform(0.0, 2.0 * math.pi)
    cx, cy = tip_px
    for petal in range(_PETALS):
        angle = phase + petal * 2.0 * math.pi / _PETALS
        px = cx + radius * 0.95 * math.cos(angle)
        py = cy + radius * 0.95 * math.sin(angle)
        draw.ellipse((px - radius * 0.8, py - radius * 0.8, px + radius * 0.8, py + radius * 0.8),
                     fill=color)
    eye = _lerp_color(color, BLOSSOM_EYE, 0.6)
    draw.ellipse((cx - radius * 0.6, cy - radius * 0.6, cx + radius * 0.6, cy + radius * 0.6),
                 fill=eye)


def _draw_seed_head(
    draw: ImageDraw.ImageDraw, tip_px: tuple[float, float], genome: Genome, node_id: int
) -> None:
    """Draw the pale seed head a tip carries once the plant has set seed.

    Only some tips bear one, chosen by ``node_id``, so the seed sits on the plant as
    unevenly as everything else it has grown.
    """
    rng = random.Random(f"seed:{node_id}")
    if rng.random() > 0.55:
        return
    radius = _SEED_RADIUS * genome.leaf_size
    cx, cy = tip_px
    for _ in range(_SEEDS_PER_HEAD):
        angle = rng.uniform(0.0, 2.0 * math.pi)
        dist = rng.uniform(0.0, radius * 1.6)
        sx, sy = cx + dist * math.cos(angle), cy + dist * math.sin(angle)
        draw.ellipse((sx - radius, sy - radius, sx + radius, sy + radius), fill=SEED_HEAD)


def _epiphyte_world_points(structure: Structure) -> dict[int, tuple[float, float]]:
    """Place the epiphyte's own coordinates into its host's space, at its limb.

    The epiphyte's germ sits at its own origin, so translating by the host node it
    settled on lands the little plant exactly on that branch.
    """
    epiphyte = structure.epiphyte
    if epiphyte is None:
        return {}
    limb = structure.nodes[epiphyte.host_node_id]
    return {node.id: (limb.x + node.x, limb.y + node.y) for node in epiphyte.structure.nodes}


def _projection(
    points: list[tuple[float, float]], vitality: float, earth_top: int
) -> tuple[Callable[[float, float], tuple[float, float]], Callable[[float], float]]:
    """Return ``(to_px, height_fraction)`` fitting ``points`` into the frame.

    ``to_px`` centres the plant horizontally, roots its base on the earth line,
    flips y so it grows upward, and sags the young (high) ends downward when the
    plant is parched. ``height_fraction`` says how far up the plant a given y sits,
    which drives both the stem gradient and that sag.
    """
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    data_w, data_h = max_x - min_x, max_y - min_y

    root_y = earth_top + _ROOT_OVERLAP
    scale_x = (_W - 2 * _PADDING) / data_w if data_w > 1e-9 else float("inf")
    scale_y = (root_y - _PADDING) / data_h if data_h > 1e-9 else float("inf")
    scale = min(scale_x, scale_y)
    if scale == float("inf"):
        scale = 1.0
    center_x = (min_x + max_x) / 2.0
    dryness = 1.0 - vitality

    def height_fraction(y: float) -> float:
        return (y - min_y) / data_h if data_h > 1e-9 else 1.0

    def to_px(x: float, y: float) -> tuple[float, float]:
        droop = _DROOP_MAX * dryness * height_fraction(y) ** 1.25
        return (_W / 2 + (x - center_x) * scale, root_y - (y - min_y) * scale + droop)

    return to_px, height_fraction


def _stem_segments(
    structure: Structure,
    pixels: dict[int, tuple[float, float]],
    heights: dict[int, float],
    vitality: float,
    max_width: float,
) -> list[Segment]:
    """Build a structure's stems as drawable segments, thickest (trunk) first.

    Width follows the pipe model — how many tips a node carries, relative to the
    whole — scaled into this structure's own range, so an epiphyte's trunk stays a
    twig. Dead wood is a constant weathered grey; living wood takes the height
    gradient, parched toward brown as vitality falls.
    """
    nodes = structure.nodes
    tip_counts = _subtree_tip_counts(structure)
    max_tips = max(tip_counts.values())
    branches = sorted(
        ((node, nodes[node.parent_id]) for node in nodes if node.parent_id is not None),
        key=lambda pair: tip_counts[pair[0].id],
        reverse=True,
    )

    segments: list[Segment] = []
    for node, parent in branches:
        if node.state is NodeState.DEAD:
            color = DEAD_WOOD
        else:
            middle = (heights[node.id] + heights[parent.id]) / 2.0
            color = _parch(_lerp_color(STEM_BOTTOM, STEM_TOP, middle), vitality)
        frac = (tip_counts[node.id] ** 0.5) / (max_tips ** 0.5)
        width = max(_MIN_STEM, _MIN_STEM + (max_width - _MIN_STEM) * frac)
        segments.append((pixels[parent.id], pixels[node.id], color, width))
    return segments


def _draw_segments(draw: ImageDraw.ImageDraw, segments: list[Segment]) -> None:
    """Stroke stem segments in order, rounding the joint where widths differ."""
    for start, end, color, width in segments:
        draw.line((start, end), fill=color, width=max(1, round(width)))
        radius = width / 2.0
        cx, cy = end
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)


def _draw_crown(
    draw: ImageDraw.ImageDraw,
    structure: Structure,
    pixels: dict[int, tuple[float, float]],
    genome: Genome,
    vitality: float,
    bloom_color: Color | None = None,
    seeded: bool = False,
    leaf_color: Color = LEAF,
) -> None:
    """Draw what the living tips carry: leaves, then any seed heads and blossoms.

    A bloom's abundance and blossom size come from ``structure.stats.bloom_intensity``
    — read straight off the already-grown structure, since this module never
    computes vitality dimensions itself, only draws them (see the module docstring).
    """
    intensity = structure.stats.bloom_intensity
    for node in structure.nodes:
        if node.state is not NodeState.TIP:
            continue
        tip_px = pixels[node.id]
        _draw_leaves(draw, tip_px, vitality, genome, node.id, leaf_color)
        if seeded:
            _draw_seed_head(draw, tip_px, genome, node.id)
        if bloom_color is not None:
            _draw_blossom(draw, tip_px, genome, node.id, bloom_color, intensity)


def _draw_structure(
    draw: ImageDraw.ImageDraw,
    structure: Structure,
    genome: Genome,
    vitality: float,
    earth_top: int,
) -> None:
    """Draw the whole plant: body and foliage, plus whatever it has earned.

    A plant in bloom carries blossoms in its own colour, one that has set seed
    carries seed heads, and a tree old enough to have taken on an epiphyte carries
    that little second plant on the limb it settled on.
    """
    epiphyte_world = _epiphyte_world_points(structure)
    points = [(node.x, node.y) for node in structure.nodes] + list(epiphyte_world.values())
    to_px, height_fraction = _projection(points, vitality, earth_top)

    pixels = {node.id: to_px(node.x, node.y) for node in structure.nodes}
    heights = {node.id: height_fraction(node.y) for node in structure.nodes}
    segments = _stem_segments(structure, pixels, heights, vitality, _MAX_STEM)

    epiphyte_pixels = {node_id: to_px(x, y) for node_id, (x, y) in epiphyte_world.items()}
    if structure.epiphyte is not None:
        epiphyte_heights = {
            node_id: height_fraction(y) for node_id, (_, y) in epiphyte_world.items()
        }
        segments += _stem_segments(
            structure.epiphyte.structure,
            epiphyte_pixels,
            epiphyte_heights,
            vitality,
            _EPIPHYTE_MAX_STEM,
        )
    _draw_segments(draw, segments)

    # A bloom that outlasts the water fades with the rest of the plant before it
    # finally drops, so a flowering channel going quiet is visible as it happens.
    bloom_color = _parch(_bloom_color(genome), vitality) if is_blooming(structure, vitality) else None
    _draw_crown(draw, structure, pixels, genome, vitality, bloom_color, has_seeded(structure))
    if structure.epiphyte is not None:
        _draw_crown(
            draw,
            structure.epiphyte.structure,
            epiphyte_pixels,
            epiphyte_genome(structure.seed),
            vitality,
            leaf_color=EPIPHYTE_LEAF,
        )
