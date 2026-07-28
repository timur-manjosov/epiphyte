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

Below the earth line sits the one thing on this plant that is not a reading of
the channel's writing at all: its root system (Phase 17). How much of it shows is
``structure.root_spread`` of the guild's voice activity, passed in beside
``moisture``; like moisture it modulates the look over a fixed body and is never
part of that body. It is deliberately the quietest treatment in this module —
roots the colour of the shadow behind the plant, fanning a little way into the
soil, plus a thickening at the very foot of the trunk — and it is strictly
additive: at a spread of ``0.0``, which is what a server that never uses voice
always gets, every drawing call below behaves exactly as it did before this
existed.

One argument to :func:`render` is not a reading of the server at all: ``wind``.
Somebody is typing in the guild right now, so the crown leans a few pixels
downwind for as long as that lasts and then stands up again — the only thing
this module draws that measures nothing, accumulates nothing and is remembered
by nothing. It is expressed as part of the projection, beside the drought sag,
because a breeze and a wilt are one posture with two causes. Both wind states
are fully deterministic, so this module's guarantee is unchanged: the same
arguments always produce the same bytes, and all that is momentary is which
arguments the caller passes.

This module has a second entry point, :func:`render_rings`, and it draws
something else entirely: a cross-section of the trunk, one ring per finished
calendar year, from :func:`structure.rings`. It takes no structure, no genome
and no moisture — the body it would draw is not the subject — and it changes
nothing about :func:`render`, which produces byte-identical output whether the
plant has rings on record or not. The two are alternatives the caller chooses
between for one rare day a year, never layers.
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
    Ring,
    Structure,
    epiphyte_genome,
    has_seeded,
    is_blooming,
    ring_layout,
    root_spread,
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

#: Colour of the root system: the same dark the plant is silhouetted against, so
#: roots read as displaced soil — a shadow under the earth line rather than a
#: drawn object competing with the body. Kept on-palette on purpose (it is
#: literally :data:`BACKGROUND`), and kept low-contrast against :data:`EARTH` on
#: purpose too: this dimension is meant to reward looking at the picture, not to
#: announce itself from across the channel.
ROOT_SHADOW = BACKGROUND
#: How many roots fan out from the trunk's foot at full spread.
_ROOT_COUNT = 6
#: Longest a root reaches into the earth band at full spread (supersampled px),
#: comfortably inside :data:`_EARTH_HEIGHT` so no root ever leaves the soil.
_ROOT_MAX_LENGTH = 46.0 * SUPERSAMPLE
#: How far a root may lean away from straight down, in degrees. Kept under the
#: 60° mark on purpose: a root that leans further than that reads as a spike
#: lying on the soil rather than as something going down into it.
_ROOT_MAX_SPLAY = 54.0
#: Widest a root is where it leaves the trunk, as a fraction of the trunk's own
#: width there — roots are always thinner than what they feed.
_ROOT_WIDTH_FRACTION = 0.45
#: Extra width (supersampled px) added at the very foot of the trunk at full
#: spread — the basal flare. Added on top of the pipe model's own width, never
#: replacing it, so the body's own proportions are untouched.
_ROOT_MAX_FLARE = 6.0 * SUPERSAMPLE
#: How far up the plant the basal flare reaches, as a fraction of its height.
#: A hard cutoff rather than an asymptotic fade, and deliberately so: stem widths
#: are rounded to whole pixels, so an asymptotic tail leaves an epsilon that can
#: still tip a rounding boundary on some twig high in the crown. Cutting it off
#: makes "voice activity never touches the crown" exact rather than approximate.
_ROOT_FLARE_REACH = 0.33
#: How fast the flare falls off across that reach. Cubic, so it is a buttress at
#: the very foot of the trunk rather than a uniform thickening of its lower third.
_ROOT_FLARE_FALLOFF = 3.0

#: Furthest the crown's highest tips lean when the air is moving (supersampled
#: px). Four — against the drought sag's fifty-eight, which is the comparison
#: that sets the scale: a gust has to be a small fraction of the posture change
#: that means the plant is in trouble, or it reads as damage instead of weather.
#: At the final image size this is four pixels of lean at the very top of a
#: full-frame tree, and one pixel at its midpoint.
#:
#: Note that the "share of the frame that changes" measure Phase 17 bounded the
#: root system with is the wrong instrument here and is deliberately not reused:
#: roots are a new object appearing in empty soil, so the area they cover *is*
#: their size, while a lean moves an object that is already there, and shifting
#: a dense crown by a single pixel already redraws every edge in it. The honest
#: bound for this effect is the displacement itself, which the two constants
#: here state exactly.
_WIND_MAX_SWAY = 4.0 * SUPERSAMPLE
#: How the lean falls off down the plant. Squared, so the trunk is effectively
#: still and only the young ends move — the same distribution the drought sag
#: uses, and the same thing a real breeze does to a tree.
_WIND_FALLOFF = 2.0

# --- The cross-section (a second picture, not a second plant) -----------------
#
# Everything above draws the plant as it stands right now. The cross-section
# below draws the opposite: the finished years behind it, one ring each, read
# from pith to bark. It shares this module's palette and nothing else — no
# projection, no pipe model, no vitality modulation — because it is not a view
# of the body at all, it is a view of the record. It is drawn square rather than
# in the plant's own 480x600 frame: a disc in a portrait frame is mostly empty
# soil, and the different shape is itself an honest signal that this is not the
# usual picture.

#: Side of the cross-section image in pixels. Square, and the same width as the
#: plant's frame, so the living message's column does not jump when it appears.
RING_SIZE = 480
#: Pale, open wood: what a quiet year lays down. Nord's parched brown, reused
#: rather than reinvented — the colour a thirsty stem already tints toward.
RING_EARLY = PARCHED
#: Tight, dark wood: what a year of sustained health lays down. The rooted stem
#: brown driven down toward the background's value; it stays a brown rather than
#: sliding blue, since wood in shadow is still wood.
RING_LATE = (52, 41, 32)
#: A drought year's ring is drawn in exactly the grey that drought's dead
#: branches are drawn in elsewhere in this module (:data:`DEAD_WOOD`). The two
#: are the same event seen from two angles, so they are not given two colours.
RING_SCAR = DEAD_WOOD
#: Bark: the rim the outermost year meets. The rooted brown of a trunk's foot.
RING_BARK = STEM_BOTTOM
#: How much of the disc's radius the bark rim takes.
_RING_BARK_SHARE = 0.06
#: Margin between the disc and the edge of the image (supersampled px).
_RING_PADDING = 34 * SUPERSAMPLE
#: Radius of the pith at the very centre, as a share of the wood's radius. The
#: first year has to start somewhere, and on a real cross-section that somewhere
#: is a small dark eye rather than a point.
_RING_PITH_SHARE = 0.045
#: How many points each ring boundary is drawn from. High enough that the wobble
#: below reads as an organic edge rather than as a polygon.
_RING_SAMPLES = 240
#: Amplitude and angular frequency of the two harmonics that keep a ring from
#: being a perfect circle. Multiplicative on the radius, so every boundary wobbles
#: by the same *shape* and rings can never cross into one another however thin
#: they get. Small: a trunk is round, just not machined.
_RING_WOBBLE: tuple[tuple[float, float], ...] = ((0.030, 2.0), (0.017, 5.0))

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


def render(
    structure: Structure,
    moisture: float,
    genome: Genome,
    voice_activity: float = 0.0,
    wind: bool = False,
) -> io.BytesIO:
    """Render a plant to a PNG and return it as a ``BytesIO``.

    ``moisture`` is the plant's current vitality (0..1) and ``genome`` its
    heritable look; together they modulate foliage, colour and posture over the
    fixed body. ``voice_activity`` (0..1) is the guild's current voice-channel
    reading and modulates the root system the same way — see
    :func:`structure.root_spread`, which turns it into how much of that root
    system shows. It defaults to ``0.0``, no root system at all, so a caller
    that does not pass it gets exactly the image this function always produced.
    Draws the Nord background and earth band, then the plant, centred and scaled
    to fit. A just-germinated plant (a single node) is drawn as a sprout — a
    sprout has no trunk to flare and no roots worth the name yet, so voice
    activity does not reach it. The returned buffer is rewound to the start.

    ``wind`` is the one argument here that is not a reading of anything (see
    :func:`structure.wind_is_stirring`): somebody is typing in the guild at this
    moment, so the crown leans a little. It defaults to ``False`` — still air —
    and the two states are each fully deterministic, so this function keeps the
    property the whole project rests on: the same inputs always draw the same
    bytes. All that is momentary is which of the two the caller asks for. A
    sprout is left out of it as well: twenty-two pixels of stem have nothing to
    sway.
    """
    vitality = max(0.0, min(1.0, moisture))
    image = Image.new("RGB", (_W, _H), BACKGROUND)
    draw = ImageDraw.Draw(image)

    earth_top = _H - _EARTH_HEIGHT
    draw.rectangle((0, earth_top, _W, _H), fill=EARTH)

    if len(structure.nodes) > 1:
        _draw_structure(
            draw, structure, genome, vitality, earth_top, root_spread(voice_activity), wind
        )
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
    points: list[tuple[float, float]], vitality: float, earth_top: int, sway: float = 0.0
) -> tuple[Callable[[float, float], tuple[float, float]], Callable[[float], float]]:
    """Return ``(to_px, height_fraction)`` fitting ``points`` into the frame.

    ``to_px`` centres the plant horizontally, roots its base on the earth line,
    flips y so it grows upward, and sags the young (high) ends downward when the
    plant is parched. ``height_fraction`` says how far up the plant a given y sits,
    which drives both the stem gradient and that sag.

    ``sway`` is the wind's signed lean, in pixels at the plant's very top,
    distributed down the body by the same height fraction the sag uses (see
    :data:`_WIND_MAX_SWAY`). It is deliberately expressed here rather than as a
    separate drawing pass: a breeze moves the whole standing plant, foliage and
    epiphyte and all, exactly as drought's sag does — the two are one posture
    with two causes. At its default ``0.0`` every coordinate this returns is
    bit-identical to the pre-wind projection.
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
        lean = sway * height_fraction(y) ** _WIND_FALLOFF
        return (_W / 2 + (x - center_x) * scale + lean, root_y - (y - min_y) * scale + droop)

    return to_px, height_fraction


def _stem_segments(
    structure: Structure,
    pixels: dict[int, tuple[float, float]],
    heights: dict[int, float],
    vitality: float,
    max_width: float,
    base_flare: float = 0.0,
) -> list[Segment]:
    """Build a structure's stems as drawable segments, thickest (trunk) first.

    Width follows the pipe model — how many tips a node carries, relative to the
    whole — scaled into this structure's own range, so an epiphyte's trunk stays a
    twig. Dead wood is a constant weathered grey; living wood takes the height
    gradient, parched toward brown as vitality falls.

    ``base_flare`` is the extra width voice activity buttresses the foot of the
    trunk with (see :data:`_ROOT_MAX_FLARE`). It is *added* to the pipe model's
    own width rather than folded into ``max_width``, so it cannot change the
    body's own proportions; it is scaled by the segment's pipe fraction, so it
    reaches only thick wood; and it stops dead at :data:`_ROOT_FLARE_REACH`, so
    every width above the plant's lower third is bit-identical whatever the
    flare. At its default ``0.0`` every width here is bit-identical, full stop.
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
        middle = (heights[node.id] + heights[parent.id]) / 2.0
        if node.state is NodeState.DEAD:
            color = DEAD_WOOD
        else:
            color = _parch(_lerp_color(STEM_BOTTOM, STEM_TOP, middle), vitality)
        frac = (tip_counts[node.id] ** 0.5) / (max_tips ** 0.5)
        flare = 0.0
        if middle < _ROOT_FLARE_REACH:
            fade = 1.0 - middle / _ROOT_FLARE_REACH
            flare = base_flare * frac * fade ** _ROOT_FLARE_FALLOFF
        width = max(_MIN_STEM, _MIN_STEM + (max_width - _MIN_STEM) * frac + flare)
        segments.append((pixels[parent.id], pixels[node.id], color, width))
    return segments


def _draw_roots(
    draw: ImageDraw.ImageDraw,
    base_px: tuple[float, float],
    trunk_width: float,
    spread: float,
    seed: int,
) -> None:
    """Draw the root system fanning from the trunk's foot into the earth band.

    ``spread`` is :func:`structure.root_spread` of the guild's voice activity and
    governs both halves of how visible this is: how far the roots reach, and how
    far their colour has moved from the soil they sit in toward
    :data:`ROOT_SHADOW`. Both scale straight off it, so the emergence past
    :data:`structure.VOICE_ROOT_THRESHOLD` is squared once more in perceived
    terms than the curve alone — a hint at first, legible only near saturation.
    At ``spread <= 0`` nothing is drawn at all.

    Splay and length are seeded by the plant's own ``seed``, so a given plant
    always has the same roots and they stay put between renders, exactly like its
    leaf placement and blossom rotations do.
    """
    if spread <= 0.0:
        return
    rng = random.Random(f"root:{seed}")
    color = _lerp_color(EARTH, ROOT_SHADOW, spread)
    base_x, base_y = base_px
    for index in range(_ROOT_COUNT):
        # Fan the roots evenly across the splay, then jitter each a little, so a
        # plant's roots are as uneven as everything else it has grown.
        even = -1.0 + 2.0 * index / (_ROOT_COUNT - 1)
        angle = math.radians(90.0 + even * _ROOT_MAX_SPLAY * rng.uniform(0.75, 1.0))
        length = _ROOT_MAX_LENGTH * spread * rng.uniform(0.6, 1.0)
        width = max(1.0, trunk_width * _ROOT_WIDTH_FRACTION * rng.uniform(0.5, 1.0))
        # Two tapering runs rather than one straight line: the root leaves the
        # trunk thick and short of its full reach, then thins to a point.
        mid_x = base_x + length * 0.55 * math.cos(angle)
        mid_y = base_y + length * 0.55 * math.sin(angle)
        end_x = base_x + length * math.cos(angle) + length * 0.2 * rng.uniform(-1.0, 1.0)
        end_y = base_y + length * math.sin(angle)
        draw.line((base_x, base_y, mid_x, mid_y), fill=color, width=max(1, round(width)))
        draw.line((mid_x, mid_y, end_x, end_y), fill=color, width=max(1, round(width * 0.5)))


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
    spread: float = 0.0,
    wind: bool = False,
) -> None:
    """Draw the whole plant: body and foliage, plus whatever it has earned.

    A plant in bloom carries blossoms in its own colour, one that has set seed
    carries seed heads, and a tree old enough to have taken on an epiphyte carries
    that little second plant on the limb it settled on.

    ``spread`` (see :func:`structure.root_spread`) buttresses the foot of the
    trunk and, below it, draws the roots — before the stems, so the trunk always
    sits over its own roots. The epiphyte is deliberately left out of both: it
    grows on a branch and never touches the soil, which is exactly what makes it
    an epiphyte.

    ``wind`` leans the standing body (see :func:`_projection`). Which way it
    leans comes from the plant's own seed, so a given individual always takes
    the same gust the same way — the same rule its leaf placement, its blossom
    rotations and its cross-section's silhouette already follow, and the reason
    a gust is a second deterministic picture rather than a random one.
    """
    epiphyte_world = _epiphyte_world_points(structure)
    points = [(node.x, node.y) for node in structure.nodes] + list(epiphyte_world.values())
    sway = _WIND_MAX_SWAY * (1.0 if structure.seed % 2 == 0 else -1.0) if wind else 0.0
    to_px, height_fraction = _projection(points, vitality, earth_top, sway)

    pixels = {node.id: to_px(node.x, node.y) for node in structure.nodes}
    heights = {node.id: height_fraction(node.y) for node in structure.nodes}
    segments = _stem_segments(structure, pixels, heights, vitality, _MAX_STEM, spread * _ROOT_MAX_FLARE)
    if spread > 0.0 and segments:
        _draw_roots(draw, pixels[0], segments[0][3], spread, structure.seed)

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


# --- The cross-section ---------------------------------------------------------
#
# Nothing below is reachable from render() and render() reaches nothing below:
# the two produce different images from different inputs, and the cross-section
# never modulates the plant's own picture the way moisture and root spread do.


def _ring_color(ring: Ring) -> Color:
    """The colour one finished year is drawn in.

    A scarred year takes :data:`RING_SCAR` outright — the same grey the branches
    that year killed are drawn in — because how *bad* it was beyond "it cost
    wood" is already said by how narrow its band is. Every other year is placed
    along the pale-to-dark ramp by its own absolute vitality, never by how it
    compares to its neighbours: a life of uniformly middling years must look
    middling all the way out, not be flattered by having nothing better to sit
    beside.
    """
    if ring.scarred:
        return RING_SCAR
    return _lerp_color(RING_EARLY, RING_LATE, max(0.0, min(1.0, ring.vitality)))


def _ring_outline(
    center: tuple[float, float], radius: float, phases: tuple[float, ...]
) -> list[tuple[float, float]]:
    """Sample one ring boundary as a slightly irregular closed curve.

    The wobble is multiplicative on ``radius`` and uses the same ``phases`` for
    every boundary in one cross-section, so all the rings share one silhouette
    and a thin ring can never cross the ring outside it however little width it
    was given. The phases come from the plant's own seed, so a given trunk is
    always the same shape between renders — the same rule the leaf placement and
    the blossom rotations already follow.
    """
    cx, cy = center
    points: list[tuple[float, float]] = []
    for index in range(_RING_SAMPLES):
        angle = 2.0 * math.pi * index / _RING_SAMPLES
        wobble = sum(
            amplitude * math.sin(frequency * angle + phase)
            for (amplitude, frequency), phase in zip(_RING_WOBBLE, phases)
        )
        reach = radius * (1.0 + wobble)
        points.append((cx + reach * math.cos(angle), cy + reach * math.sin(angle)))
    return points


def render_rings(rings: tuple[Ring, ...], seed: int) -> io.BytesIO:
    """Render a trunk's cross-section to a PNG and return it as a ``BytesIO``.

    ``rings`` are the finished years, oldest first, exactly as
    :func:`structure.rings` returns them; ``seed`` is the plant's own, which
    fixes the silhouette so the same trunk is recognisable year after year. The
    bands are laid out by :func:`structure.ring_layout` — that is where a good
    year becomes a wide band — and coloured by :func:`_ring_color`, which is
    where a good year becomes dark, tight wood and a drought year becomes the
    grey of the branches it killed.

    Drawn from the bark inward, each ring a filled shape the next one paints
    over, which is both the cheapest way to get exact contiguous bands and the
    order the wood was actually laid down in reverse. Callers must not ask for
    an empty cross-section: a plant with no finished year has no rings to show
    and the caller decides that before ever getting here (see ``bot.py``'s
    ``_cross_section``). The returned buffer is rewound to the start.
    """
    size = RING_SIZE * SUPERSAMPLE
    image = Image.new("RGB", (size, size), BACKGROUND)
    draw = ImageDraw.Draw(image)

    center = (size / 2.0, size / 2.0)
    disc = size / 2.0 - _RING_PADDING
    wood = disc * (1.0 - _RING_BARK_SHARE)
    rng = random.Random(f"rings:{seed}")
    phases = tuple(rng.uniform(0.0, 2.0 * math.pi) for _ in _RING_WOBBLE)

    draw.polygon(_ring_outline(center, disc, phases), fill=RING_BARK)
    for ring, (_, outer) in zip(reversed(rings), reversed(ring_layout(rings))):
        draw.polygon(_ring_outline(center, wood * outer, phases), fill=_ring_color(ring))
    draw.polygon(_ring_outline(center, wood * _RING_PITH_SHARE, phases), fill=RING_LATE)

    image = image.resize((RING_SIZE, RING_SIZE), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
