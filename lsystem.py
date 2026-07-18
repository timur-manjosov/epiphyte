"""Pure L-system logic for Epiphyte.

No side effects, no randomness, no ``import discord`` and no Pillow. Given the
same inputs these functions always return the same outputs, which makes them
testable with pytest without drawing anything.

The plant is a single branching species described by an axiom and replacement
rules over the alphabet ``F`` (draw forward), ``+`` / ``-`` (turn) and ``[`` /
``]`` (push / pop turtle state). ``X`` is a non-drawing structural variable that
merely shapes the recursion.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from moisture import Stage

#: Axiom and replacement rules for the one plant species (classic fractal plant).
PLANT_AXIOM = "X"
PLANT_RULES: dict[str, str] = {
    "X": "F+[[X]-X]-F[-FX]+X",
    "F": "FF",
}
#: Turn angle in degrees applied by ``+`` and ``-``.
PLANT_ANGLE = 25.0
#: Length of a single ``F`` step. Absolute value is irrelevant — the renderer
#: scales the plant to fit — but it fixes the relative geometry.
PLANT_STEP = 10.0

#: Moisture growth stage mapped to L-system recursion depth: more moisture means
#: a deeper expansion and thus a more complex shape.
STAGE_DEPTHS: dict[Stage, int] = {
    Stage.WITHERED: 2,
    Stage.DRY: 3,
    Stage.HEALTHY: 4,
    Stage.THRIVING: 5,
}


class Point(NamedTuple):
    """A 2D point in turtle space (``+y`` points up)."""

    x: float
    y: float


class Segment(NamedTuple):
    """A straight line segment drawn by a single ``F`` step."""

    start: Point
    end: Point


def expand(axiom: str, rules: dict[str, str], depth: int) -> str:
    """Apply ``rules`` to ``axiom`` ``depth`` times and return the command string.

    Every symbol is replaced simultaneously per iteration; a symbol without a
    rule is left unchanged. ``depth`` of ``0`` returns the axiom verbatim. Pure
    and deterministic.
    """
    result = axiom
    for _ in range(depth):
        result = "".join(rules.get(symbol, symbol) for symbol in result)
    return result


def interpret(commands: str, angle_degrees: float, step_length: float) -> list[Segment]:
    """Turn a command string into a list of line segments via a turtle.

    ``F`` draws one step forward, ``+`` / ``-`` turn left / right by
    ``angle_degrees``, and ``[`` / ``]`` push / pop the turtle's position and
    heading. Any other symbol (such as ``X``) is a no-op. The turtle starts at
    the origin pointing up. Pure — no graphics involved.
    """
    segments: list[Segment] = []
    x, y = 0.0, 0.0
    heading = 90.0  # degrees, measured counter-clockwise from the +x axis
    stack: list[tuple[float, float, float]] = []

    for symbol in commands:
        if symbol == "F":
            radians = math.radians(heading)
            new_x = x + step_length * math.cos(radians)
            new_y = y + step_length * math.sin(radians)
            segments.append(Segment(Point(x, y), Point(new_x, new_y)))
            x, y = new_x, new_y
        elif symbol == "+":
            heading += angle_degrees
        elif symbol == "-":
            heading -= angle_degrees
        elif symbol == "[":
            stack.append((x, y, heading))
        elif symbol == "]":
            x, y, heading = stack.pop()

    return segments


def depth_for_stage(stage: Stage) -> int:
    """Map a moisture growth stage to its L-system recursion depth."""
    return STAGE_DEPTHS[stage]
