"""Препроцессор плана: стороны, проёмы, вход, запретные зоны, отказы (plan-input.md)."""

from pathlib import Path

import pytest

from genfacade.plan.gaps import find_gaps
from genfacade.plan.genplan_svg import Box, PlanError
from genfacade.plan.outline import straighten

ROOT = Path(__file__).parents[2]
DOORS = ROOT / "tests" / "fixtures" / "genplan"
M = 0.01  # у синтетических коробок вход 90 px — 1 px = 0.01 м


def _openings(side):
    return [(o.kind, round(o.x_m, 3), round(o.width_m, 3)) for o in side.openings]


def _zones(side):
    return [(round(z.x0_m, 2), round(z.x1_m, 2)) for z in side.forbidden]


@pytest.mark.parametrize(
    ("name", "normal", "x_m"),
    [
        # верхняя стена, снаружи с севера слева восток: от x = 500 до края разрыва 340
        ("door_top", (0.0, 1.0), (500 - 340) * M),
        # левая стена, снаружи с запада слева север (верх SVG): от y = 100 до 250
        ("door_left", (-1.0, 0.0), (250 - 100) * M),
    ],
)
def test_entrance_side_and_x_seen_from_outside(preprocess_svg, name, normal, x_m):
    plan = preprocess_svg(DOORS / f"{name}.svg")
    assert plan.scale_m_per_px == pytest.approx(M)
    side = plan.sides[0]
    assert side.has_entrance and side.orientation == normal
    assert _openings(side) == [("entrance", round(x_m, 3), 0.9)]


def test_sides_clockwise_from_entrance(preprocess_svg):
    plan = preprocess_svg(DOORS / "door_top.svg")
    assert [s.orientation for s in plan.sides] == [(0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0)]
    assert [s.length_m for s in plan.sides] == pytest.approx([4.0] * 4)


def test_second_outer_door_sealed_in_blind_mode(preprocess_svg):
    plan = preprocess_svg(DOORS / "door_edge.svg", mode="blind")
    door = next(o for o in plan.openings if o.kind == "door")
    assert door.sealed and door.rect in plan.walls
    assert sum(len(s.openings) for s in plan.sides) == 1


def test_house_forbidden_zones(preprocess_svg):
    sides = preprocess_svg(DOORS / "house.svg").sides
    # вход-сторона — левая; внутренняя стена y = 310 прорисована насквозь до наружной грани
    assert _zones(sides[0]) == [(1.6, 1.7)]
    # верх: стена x = 330 заходит в полосу окна — дефект GenPlan, зона внутри окна остаётся
    assert _zones(sides[1]) == [(1.61, 1.7)]
    window = sides[1].openings[0]
    assert window.x_m < 1.61 and 1.7 < window.x_m + window.width_m
    assert _zones(sides[2]) == []
    assert _zones(sides[3]) == [(2.0, 2.1)]  # стена x = 300 до наружной грани снизу


def test_false_genplan_window_ignored(preprocess_svg):
    """Decorator GenPlan залил окном комнату между стенами равной длины — это не проём."""
    plan = preprocess_svg(DOORS / "house.svg")
    assert sorted(o.kind for o in plan.openings) == ["entrance", "window", "window"]
    assert all(o.rect.x1_m - o.rect.x0_m < 0.2 or o.rect.y1_m - o.rect.y0_m < 0.2
               for o in plan.openings)  # все проёмы — в толще стены


def test_duplicated_inner_walls_give_one_zone(box_svg, preprocess_svg):
    inner = [(300, 115, 310, 300), (302, 115, 312, 280)]  # векторизация дублирует внахлёст
    plan = preprocess_svg(box_svg({"bottom": [(200, 290)]}, inner=inner))
    top = next(s for s in plan.sides if s.orientation == (0.0, 1.0))
    assert _zones(top) == [(1.88, 2.0)]


def test_walls_only_plan_narrowest_gap_is_entrance(box_svg, preprocess_svg):
    # план до decorator GenPlan: разрывы без окон и створок
    plan = preprocess_svg(box_svg({"bottom": [(150, 330)], "right": [(200, 290)]}))
    kinds = sorted((o.kind, round(o.rect.x1_m - o.rect.x0_m + o.rect.y1_m - o.rect.y0_m, 2))
                   for o in plan.openings)
    # вход — 90 px (0.9 м по масштабу), окно — 180 px, толщина стены 15 px
    assert kinds == [("entrance", 1.05), ("window", 1.95)]


def test_outer_door_wins_over_narrower_window(preprocess_svg):
    text = (DOORS / "door_top.svg").read_text()
    # узкое окно 40 px в нижней стене: самый узкий разрыв, но вход — дверь
    text = text.replace('<rect x="100" y="485" width="400" height="15" fill="#000000" />',
                        '<rect x="100" y="485" width="200" height="15" fill="#000000" />'
                        '<rect x="340" y="485" width="160" height="15" fill="#000000" />'
                        '<rect x="300" y="485" width="40" height="15" fill="#99ccff" />')
    plan = preprocess_svg(text)
    assert sorted(o.kind for o in plan.openings) == ["entrance", "window"]
    assert plan.sides[0].orientation == (0.0, 1.0)


def test_seam_is_not_an_opening(box_svg, preprocess_svg):
    plan = preprocess_svg(box_svg({"bottom": [(200, 290)], "top": [(300, 305)]}))
    assert [o.kind for o in plan.openings] == ["entrance"]
    assert len(plan.sides) == 4


def test_open_contour_rejected(box_svg, preprocess_svg):
    walls_missing_side = box_svg({"right": [(100, 500)], "bottom": [(200, 290)]})
    with pytest.raises(PlanError, match="не замкнулся"):
        preprocess_svg(walls_missing_side)


def test_disconnected_parts_rejected(box_svg, preprocess_svg):
    # не на одной линии со стенами коробки — иначе разрыв между ними честно перекрывается
    far = [(530, 200, 590, 210), (530, 200, 540, 400)]
    with pytest.raises(PlanError, match="не связаны"):
        preprocess_svg(box_svg({"bottom": [(200, 290)]}, inner=far))


def test_straighten_removes_pixel_jog():
    # верхняя грань из кусков толщиной 16 и 17 px: ступенька в 1 px
    ring = [(0, 0), (0, 100), (50, 100), (50, 101), (200, 101), (200, 0)]
    assert straighten(ring, jog_px=4) == [(0, 0), (0, 101), (200, 101), (200, 0)]


def test_inner_gap_without_door_is_not_an_opening(box_svg, preprocess_svg):
    # внутренняя стена с разрывом 50 px, створки нет: проход, а не проём фасада
    inner = [(300, 115, 310, 250), (300, 300, 310, 485)]
    plan = preprocess_svg(box_svg({"bottom": [(200, 290)]}, inner=inner))
    assert [o.kind for o in plan.openings] == ["entrance"]


@pytest.mark.parametrize(("y0", "gaps"), [(203, 1), (207, 0)], ids=["overlap-70%", "overlap-30%"])
def test_collinear_needs_half_thickness_overlap(cfg, y0, gaps):
    # две горизонтальные стены толщиной 10 px, сдвинутые по y на 3 и на 7 px
    walls = [Box(150, 200, 250, 210), Box(300, y0, 400, y0 + 10)]
    assert len(find_gaps(walls, cfg.plan.gaps)) == gaps
