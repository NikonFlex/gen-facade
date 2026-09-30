"""Критерии приёмки specs/plan-input.md — препроцессор плана (шаг 2, gf#14)."""

from pathlib import Path

import pytest

from genfacade import config
from genfacade.plan.gaps import find_gaps
from genfacade.plan.genplan_svg import PlanError, parse

EXAMPLE = Path(__file__).parents[2] / "materials" / "genplan-plan-example.svg"
CANVAS_PX = 1024
ACCURACY_PX = 2  # «все проёмы из SVG с точностью до 2 px»
# Проёмы примера в пикселях SVG (x0, y0, x1, y1): окна — <rect> #99ccff, вход — разрыв
# левой стены со створкой, прочитаны из файла.
EXAMPLE_OPENINGS = {
    ("window", (501, 300, 784, 317)),
    ("window", (187, 593, 203, 781)),
    ("entrance", (187, 368, 203, 486)),
}


def _to_svg_px(rect, scale: float) -> tuple[float, ...]:
    """Метры плана (y вверх) → пиксели SVG (y вниз)."""
    return (rect.x0_m / scale, CANVAS_PX - rect.y1_m / scale,
            rect.x1_m / scale, CANVAS_PX - rect.y0_m / scale)


def test_example_contour_sides_and_openings(preprocess_svg):
    plan = preprocess_svg(EXAMPLE)
    assert len(plan.outline) == 4 and len(plan.sides) == 4
    got = [(o.kind, _to_svg_px(o.rect, plan.scale_m_per_px)) for o in plan.openings]
    assert len(got) == len(EXAMPLE_OPENINGS)
    for kind, want in EXAMPLE_OPENINGS:
        assert any(k == kind and _close(px, want) for k, px in got), f"{kind} {want}: {got}"


def _close(px: tuple[float, ...], want: tuple[float, ...]) -> bool:
    return all(abs(a - b) <= ACCURACY_PX for a, b in zip(px, want, strict=True))


def test_box_without_gaps_has_no_openings(box_svg, preprocess_svg):
    # У правила GenPlan здесь два ложных проёма: верхняя и нижняя стены равной длины
    # (decorator.find_openings) — поперёк всего дома.
    svg = box_svg({})
    assert find_gaps(parse(svg).walls, config.load().plan.gaps) == []
    with pytest.raises(PlanError, match="нет входа"):
        preprocess_svg(svg)


def test_blind_mode_keeps_only_entrance(preprocess_svg):
    plan = preprocess_svg(EXAMPLE, mode="blind")
    visible = [o for o in plan.openings if o.external and not o.sealed]
    assert [o.kind for o in visible] == ["entrance"]
    on_sides = [o for s in plan.sides for o in s.openings]
    assert [o.kind for o in on_sides] == ["entrance"]


def test_plan_without_entrance_rejected_with_reason(box_svg, preprocess_svg):
    with pytest.raises(PlanError, match="нет входа: на наружном контуре ни одного разрыва"):
        preprocess_svg(box_svg({}, inner=[(300, 115, 310, 300)]))
