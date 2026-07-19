"""Rendering for Epiphyte: turn a plant structure into a PNG (Pillow I/O).

This module only draws. It performs no growth computation — it receives an
already-grown :class:`structure.Structure` and paints its body in the Nord colour
scheme. Kept separate so the pure logic stays free of any Pillow dependency.

Stem thickness follows the pipe model: a node's width is derived from how many
tips (terminal endpoints) its subtree carries, so the trunk that feeds the whole
crown is thick and the fine twigs are thin. Colour runs along height, from rooted
brown at the base to living teal at the top.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from structure import Node, Structure

# Nord palette (RGB), matching the table in CLAUDE.md.
BACKGROUND = (46, 52, 64)    # #2E3440
EARTH = (59, 66, 82)         # #3B4252
STEM_BOTTOM = (94, 74, 59)   # #5E4A3B rooted brown
STEM_TOP = (143, 188, 187)   # #8FBCBB living teal
ACCENT = (136, 192, 208)     # #88C0D0 bud

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

Color = tuple[int, int, int]


def _lerp_color(low: Color, high: Color, t: float) -> Color:
    """Linearly interpolate between two RGB colours; ``t`` is clamped to [0, 1]."""
    t = max(0.0, min(1.0, t))
    return tuple(round(a + (b - a) * t) for a, b in zip(low, high))  # type: ignore[return-value]


def render(structure: Structure) -> io.BytesIO:
    """Render a plant ``structure`` to a PNG and return it as a ``BytesIO``.

    Draws the Nord background and earth band, then the plant body, centred and
    scaled to fit. A just-germinated plant (a single node) is drawn as a sprout.
    The returned buffer is rewound to the start.
    """
    image = Image.new("RGB", (_W, _H), BACKGROUND)
    draw = ImageDraw.Draw(image)

    earth_top = _H - _EARTH_HEIGHT
    draw.rectangle((0, earth_top, _W, _H), fill=EARTH)

    if len(structure.nodes) > 1:
        _draw_structure(draw, structure, earth_top)
    else:
        _draw_sprout(draw, earth_top)

    image = image.resize((WIDTH, HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _draw_sprout(draw: ImageDraw.ImageDraw, earth_top: int) -> None:
    """Draw a tiny fresh sprout for a just-germinated, single-node plant."""
    base_x = _W / 2
    root_y = earth_top + _ROOT_OVERLAP
    tip_y = root_y - 22 * SUPERSAMPLE
    draw.line((base_x, root_y, base_x, tip_y), fill=STEM_TOP, width=round(_MIN_STEM * 2))
    radius = 5 * SUPERSAMPLE
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


def _draw_structure(draw: ImageDraw.ImageDraw, structure: Structure, earth_top: int) -> None:
    """Draw the plant body: one line per node-to-parent link, pipe-model width."""
    nodes = structure.nodes
    tip_counts = _subtree_tip_counts(structure)
    max_tips = max(tip_counts.values())

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

    def to_px(node: Node) -> tuple[float, float]:
        # Centre horizontally, root the base on the earth line, flip y so the
        # plant grows upward in the image.
        return (
            _W / 2 + (node.x - center_x) * scale,
            root_y - (node.y - min_y) * scale,
        )

    def width_for(node_id: int) -> float:
        frac = (tip_counts[node_id] ** 0.5) / (max_tips ** 0.5)
        return max(_MIN_STEM, _MIN_STEM + (_MAX_STEM - _MIN_STEM) * frac)

    def height_fraction(y: float) -> float:
        return (y - min_y) / data_h if data_h > 1e-9 else 1.0

    pixels = {node.id: to_px(node) for node in nodes}

    # Draw thickest (trunk) first so the fine twigs sit cleanly on top.
    ordered = sorted(
        (node for node in nodes if node.parent_id is not None),
        key=lambda n: tip_counts[n.id],
        reverse=True,
    )
    for node in ordered:
        parent_px = pixels[node.parent_id]  # type: ignore[index]
        node_px = pixels[node.id]
        t = height_fraction((node.y + nodes[node.parent_id].y) / 2.0)  # type: ignore[index]
        color = _lerp_color(STEM_BOTTOM, STEM_TOP, t)
        width = width_for(node.id)
        draw.line((parent_px, node_px), fill=color, width=max(1, round(width)))
        # A dot at the joint rounds the corner where segments of unequal width meet.
        radius = width / 2.0
        cx, cy = node_px
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
