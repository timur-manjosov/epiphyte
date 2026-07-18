"""Rendering for Epiphyte: turn pure geometry into a PNG (Pillow I/O).

This module only draws. It performs no L-system computation — it receives the
already-computed line segments and paints them in the Nord colour scheme. Kept
separate so the pure logic stays free of any Pillow dependency.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from lsystem import Point, Segment

# Nord palette (RGB), matching the table in CLAUDE.md.
BACKGROUND = (46, 52, 64)    # #2E3440
EARTH = (59, 66, 82)         # #3B4252
STEM_BOTTOM = (94, 74, 59)   # #5E4A3B rooted brown
STEM_TOP = (143, 188, 187)   # #8FBCBB living teal
LEAF = (163, 190, 140)       # #A3BE8C
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
#: Height fraction above which a tip is drawn as a bright accent bud, not a leaf.
_ACCENT_ABOVE = 0.82

Color = tuple[int, int, int]


def _lerp_color(low: Color, high: Color, t: float) -> Color:
    """Linearly interpolate between two RGB colours; ``t`` is clamped to [0, 1]."""
    t = max(0.0, min(1.0, t))
    return tuple(round(a + (b - a) * t) for a, b in zip(low, high))  # type: ignore[return-value]


def render(segments: list[Segment]) -> io.BytesIO:
    """Render the plant segments to a PNG and return it as a ``BytesIO``.

    Draws the Nord background and earth band, then the plant (if any segments
    were given), centred and scaled to fit. The buffer is rewound to the start.
    """
    image = Image.new("RGB", (_W, _H), BACKGROUND)
    draw = ImageDraw.Draw(image)

    earth_top = _H - _EARTH_HEIGHT
    draw.rectangle((0, earth_top, _W, _H), fill=EARTH)

    if segments:
        _draw_plant(draw, segments, earth_top)

    image = image.resize((WIDTH, HEIGHT), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def _draw_plant(draw: ImageDraw.ImageDraw, segments: list[Segment], earth_top: int) -> None:
    """Draw the stems (gradient), leaves and accent buds of the plant."""
    xs = [coord for seg in segments for coord in (seg.start.x, seg.end.x)]
    ys = [coord for seg in segments for coord in (seg.start.y, seg.end.y)]
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

    def to_px(point: Point) -> tuple[float, float]:
        # Centre horizontally, root the base on the earth line, flip y so the
        # plant grows upward in the image.
        return (
            _W / 2 + (point.x - center_x) * scale,
            root_y - (point.y - min_y) * scale,
        )

    def height_fraction(y: float) -> float:
        return (y - min_y) / data_h if data_h > 1e-9 else 1.0

    # Stems: brown at the base fading to living teal at the top, thicker below.
    for seg in segments:
        t = height_fraction((seg.start.y + seg.end.y) / 2.0)
        color = _lerp_color(STEM_BOTTOM, STEM_TOP, t)
        width = max(SUPERSAMPLE, round((4 - 3 * t) * SUPERSAMPLE))
        draw.line((to_px(seg.start), to_px(seg.end)), fill=color, width=width)

    # Leaves at terminal tips; the highest tips become bright accent buds.
    starts = {(round(seg.start.x, 6), round(seg.start.y, 6)) for seg in segments}
    leaf_r = 5 * SUPERSAMPLE
    bud_r = 4 * SUPERSAMPLE
    for seg in segments:
        if (round(seg.end.x, 6), round(seg.end.y, 6)) in starts:
            continue  # this endpoint continues into another segment — not a tip
        if height_fraction(seg.end.y) > _ACCENT_ABOVE:
            color, radius = ACCENT, bud_r
        else:
            color, radius = LEAF, leaf_r
        px, py = to_px(seg.end)
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)
