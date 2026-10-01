"""Критерии приёмки specs/plan-input.md — препроцессор плана (шаг 2) на простом доме (gf#58)."""

import pytest

from genfacade import config
from genfacade.plan.gaps import find_gaps
from genfacade.plan.genplan_svg import PlanError, parse
from genfacade.schema import Mode, OpeningKind

CANVAS_H = 700
ACCURACY_PX = 2  # «все проёмы из SVG с точностью до 2 px»
# Проёмы простого дома в пикселях SVG (x0, y0, x1, y1): окна — <rect> #99ccff в разрыве
# стены, вход — разрыв нижней стены со створкой (tests/fixtures/make_simple_house.py).
OPENINGS = {
    (OpeningKind.WINDOW, (250, 585, 370, 600)), (OpeningKind.WINDOW, (100, 350, 115, 450)),
    (OpeningKind.WINDOW, (1085, 250, 1100, 400)), (OpeningKind.WINDOW, (600, 100, 800, 115)),
    (OpeningKind.ENTRANCE, (800, 585, 890, 600)),
}
# Та же коробка без единого разрыва: четыре стены целиком.
BOX = ('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700" viewBox="0 0 1200 700">'
       '<rect x="100" y="100" width="1000" height="15" fill="#000000" />'
       '<rect x="100" y="585" width="1000" height="15" fill="#000000" />'
       '<rect x="100" y="100" width="15" height="500" fill="#000000" />'
       '<rect x="1085" y="100" width="15" height="500" fill="#000000" /></svg>')


def _to_svg_px(rect, scale: float) -> tuple[float, ...]:
    """Метры плана (y вверх) → пиксели SVG (y вниз)."""
    return (rect.x0_m / scale, CANVAS_H - rect.y1_m / scale,
            rect.x1_m / scale, CANVAS_H - rect.y0_m / scale)


def _close(px: tuple[float, ...], want: tuple[float, ...]) -> bool:
    return all(abs(a - b) <= ACCURACY_PX for a, b in zip(px, want, strict=True))


def test_contour_sides_and_openings(preprocess_svg):
    plan = preprocess_svg()
    assert len(plan.outline) == 4 and len(plan.sides) == 4
    got = [(o.kind, _to_svg_px(o.rect, plan.scale_m_per_px)) for o in plan.openings]
    assert len(got) == len(OPENINGS)
    for kind, want in OPENINGS:
        assert any(k == kind and _close(px, want) for k, px in got), f"{kind} {want}: {got}"


def test_box_without_gaps_has_no_openings(preprocess_svg):
    # У правила GenPlan здесь два ложных проёма: противоположные стены равной длины
    # (decorator.find_openings) — поперёк всего дома (проверено запуском, gf#14).
    assert find_gaps(parse(BOX).walls, config.load().plan.gaps) == []
    with pytest.raises(PlanError, match="нет входа"):
        preprocess_svg(BOX)


def test_blind_mode_keeps_only_entrance(preprocess_svg):
    plan = preprocess_svg(mode=Mode.BLIND)
    visible = [o for o in plan.openings if o.external and not o.sealed]
    assert [o.kind for o in visible] == [OpeningKind.ENTRANCE]
    assert [o.kind for s in plan.sides for o in s.openings] == [OpeningKind.ENTRANCE]


def test_plan_without_entrance_rejected_with_reason(preprocess_svg):
    with pytest.raises(PlanError, match="нет входа: на наружном контуре ни одного разрыва"):
        preprocess_svg(BOX)
