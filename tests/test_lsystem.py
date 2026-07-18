"""Tests for the pure L-system logic. No Pillow, no Discord."""

import pytest

from lsystem import (
    PLANT_AXIOM,
    PLANT_RULES,
    depth_for_stage,
    expand,
    interpret,
)
from moisture import Stage

#: A small branching ruleset whose expansions are easy to verify by hand.
BRANCHING_RULES = {"F": "F[+F]F"}


def test_expand_depth_zero_is_axiom() -> None:
    assert expand("F", BRANCHING_RULES, 0) == "F"
    assert expand(PLANT_AXIOM, PLANT_RULES, 0) == "X"


def test_expand_branching_exact_to_depth_two() -> None:
    assert expand("F", BRANCHING_RULES, 1) == "F[+F]F"
    assert expand("F", BRANCHING_RULES, 2) == "F[+F]F[+F[+F]F]F[+F]F"


def test_expand_plant_first_step_exact() -> None:
    assert expand(PLANT_AXIOM, PLANT_RULES, 1) == "F+[[X]-X]-F[-FX]+X"


def test_expand_trivial_ruleset() -> None:
    # A symbol without a rule is left unchanged; the classic algae system grows.
    assert expand("A", {"A": "AB", "B": "A"}, 0) == "A"
    assert expand("A", {"A": "AB", "B": "A"}, 1) == "AB"
    assert expand("A", {"A": "AB", "B": "A"}, 2) == "ABA"


def _brackets_balanced(commands: str) -> bool:
    """True if every prefix has non-negative bracket depth and totals zero."""
    depth = 0
    for symbol in commands:
        if symbol == "[":
            depth += 1
        elif symbol == "]":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def test_plant_brackets_always_balanced() -> None:
    for depth in range(5):
        assert _brackets_balanced(expand(PLANT_AXIOM, PLANT_RULES, depth))


def test_segment_count_increases_with_depth() -> None:
    counts = [
        len(interpret(expand(PLANT_AXIOM, PLANT_RULES, depth), 25.0, 10.0))
        for depth in range(1, 5)
    ]
    assert all(later > earlier for earlier, later in zip(counts, counts[1:]))


def test_interpret_single_forward() -> None:
    segments = interpret("F", 90.0, 10.0)
    assert len(segments) == 1
    assert segments[0].start == pytest.approx((0.0, 0.0))
    assert segments[0].end == pytest.approx((0.0, 10.0))


def test_interpret_ignores_non_drawing_symbols() -> None:
    # X is a structural variable: it draws nothing.
    assert interpret("X", 90.0, 10.0) == []
    # Two forwards separated by X stay collinear.
    segments = interpret("FXF", 90.0, 10.0)
    assert len(segments) == 2
    assert segments[1].end == pytest.approx((0.0, 20.0))


def test_interpret_brackets_restore_state() -> None:
    # After the branch closes, drawing resumes from the pushed position/heading.
    segments = interpret("F[+F]F", 90.0, 10.0)
    assert len(segments) == 3
    assert segments[2].start == pytest.approx((0.0, 10.0))
    assert segments[2].end == pytest.approx((0.0, 20.0))


def test_depth_increases_with_stage() -> None:
    depths = [
        depth_for_stage(stage)
        for stage in (Stage.WITHERED, Stage.DRY, Stage.HEALTHY, Stage.THRIVING)
    ]
    assert all(later > earlier for earlier, later in zip(depths, depths[1:]))
