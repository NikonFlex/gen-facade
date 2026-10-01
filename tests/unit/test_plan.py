"""Препроцессор плана на простом доме: стороны, проёмы, вход, запретные зоны, отказы.

Частные случаи — правки простого плана (фикстура simple_svg): внутренние стены, ложное окно
GenPlan, шов, снятая стена. Отдельных планов нет (gf#58).
"""

import pytest

from genfacade.plan.gaps import find_gaps
from genfacade.plan.genplan_svg import Box, PlanError
from genfacade.plan.outline import straighten

LEAF = '<rect x="800" y="495" width="5" height="90" fill="#000000" />'
ARC = ('<path d="M890.0,585.0 A90,90,0,0,0,800.0,495.0" stroke="#000000" fill="none" '
       'stroke-width="5" />')
TOP_LEFT = '<rect x="100" y="100" width="500" height="15" fill="#000000" />'
BLUE = ['<rect x="250" y="585" width="120" height="15" fill="#99ccff" />',
        '<rect x="100" y="350" width="15" height="100" fill="#99ccff" />',
        '<rect x="1085" y="250" width="15" height="150" fill="#99ccff" />',
        '<rect x="600" y="100" width="200" height="15" fill="#99ccff" />']
RIGHT = ['<rect x="1085" y="100" width="15" height="150" fill="#000000" />',
         '<rect x="1085" y="400" width="15" height="200" fill="#000000" />']


def _openings(side):
    return [(o.kind, round(o.x_m, 3), round(o.width_m, 3)) for o in side.openings]


def _zones(side):
    return [(round(z.x0_m, 2), round(z.x1_m, 2)) for z in side.forbidden]


def _with(*rects: tuple[float, float, float, float]) -> tuple[str, str]:
    """Замена для simple_svg: добавить чёрные прямоугольники (x0, y0, x1, y1) перед створкой."""
    extra = "".join(
        f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="#000000" />\n'
        for x0, y0, x1, y1 in rects)
    return LEAF, extra + LEAF


def test_sides_and_openings_seen_from_outside(preprocess_svg):
    """x — от левого края стороны, если смотреть снаружи; стороны по часовой от входа."""
    plan = preprocess_svg()
    assert plan.scale_m_per_px == pytest.approx(0.01)  # вход 90 px = 0.9 м
    assert [s.orientation for s in plan.sides] == [(0.0, -1.0), (-1.0, 0.0), (0.0, 1.0), (1.0, 0.0)]
    assert [s.length_m for s in plan.sides] == pytest.approx([10, 5, 10, 5])
    assert [_openings(s) for s in plan.sides] == [
        [("window", 1.5, 1.2), ("entrance", 7.0, 0.9)],  # низ: снаружи с юга слева запад
        [("window", 2.5, 1.0)],                          # лево: слева север
        [("window", 3.0, 2.0)],                          # верх: слева восток
        [("window", 2.0, 1.5)],                          # право: слева юг
    ]
    assert [s.has_entrance for s in plan.sides] == [True, False, False, False]


def test_forbidden_zones(simple_svg, preprocess_svg):
    # сверху — стена от внутренней грани и её дубль внахлёст (векторизация GenPlan так делает),
    # снизу — стена, прорисованная насквозь до наружной грани
    svg = simple_svg(_with((500, 115, 510, 400), (502, 115, 512, 380), (450, 300, 460, 600)))
    sides = preprocess_svg(svg).sides
    assert _zones(sides[2]) == [(5.88, 6.0)]  # один интервал на дубль
    assert _zones(sides[0]) == [(3.5, 3.6)]
    assert _zones(sides[1]) == _zones(sides[3]) == []


def test_false_genplan_window_ignored(simple_svg, preprocess_svg):
    """Голубая заливка поперёк дома от стены до стены — так decorator GenPlan рисует ложный
    проём между противоположными стенами равной длины (gf#36)."""
    false = '<rect x="200" y="115" width="200" height="470" fill="#99ccff" />'
    svg = simple_svg(("</svg>", false + "</svg>"))
    plan = preprocess_svg(svg)
    assert sorted(o.kind for o in plan.openings) == ["entrance"] + ["window"] * 4


def test_walls_only_plan_narrowest_gap_is_entrance(simple_svg, preprocess_svg):
    # план до decorator GenPlan: разрывы без окон и створки
    plan = preprocess_svg(simple_svg((LEAF, ""), (ARC, ""), *[(b, "") for b in BLUE]))
    assert sorted(o.kind for o in plan.openings) == ["entrance"] + ["window"] * 4
    assert _openings(plan.sides[0])[1] == ("entrance", 7.0, 0.9)


def test_outer_door_wins_over_narrower_window(simple_svg, preprocess_svg):
    # окно снизу сужено до 70 px — уже входа, но вход — разрыв со створкой
    svg = simple_svg(('<rect x="100" y="585" width="150"', '<rect x="100" y="585" width="200"'),
                     (BLUE[0], '<rect x="300" y="585" width="70" height="15" fill="#99ccff" />'))
    assert _openings(preprocess_svg(svg).sides[0]) == [("window", 2.0, 0.7), ("entrance", 7.0, 0.9)]


def test_seam_is_not_an_opening(simple_svg, preprocess_svg):
    halves = ('<rect x="100" y="100" width="200" height="15" fill="#000000" />'
              '<rect x="305" y="100" width="295" height="15" fill="#000000" />')
    plan = preprocess_svg(simple_svg((TOP_LEFT, halves)))
    assert len(plan.openings) == 5 and len(plan.sides) == 4


def test_inner_gap_without_door_is_not_an_opening(simple_svg, preprocess_svg):
    # внутренняя стена с разрывом 50 px, створки нет: проход, а не проём фасада
    plan = preprocess_svg(simple_svg(_with((500, 115, 510, 250), (500, 300, 510, 585))))
    assert len(plan.openings) == 5


def test_open_contour_rejected(simple_svg, preprocess_svg):
    svg = simple_svg(*[(r, "") for r in RIGHT], (BLUE[2], ""))
    with pytest.raises(PlanError, match="не замкнулся"):
        preprocess_svg(svg)


def test_disconnected_parts_rejected(simple_svg, preprocess_svg):
    # не на одной линии со стенами дома — иначе разрыв между ними честно перекрывается
    with pytest.raises(PlanError, match="не связаны"):
        preprocess_svg(simple_svg(_with((1120, 150, 1190, 160), (1120, 150, 1130, 690))))


def test_empty_plan_rejected(preprocess_svg):
    with pytest.raises(PlanError, match="нет ни одной стены"):
        preprocess_svg('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>')


def test_straighten_removes_pixel_jog():
    # верхняя грань из кусков толщиной 16 и 17 px: ступенька в 1 px
    ring = [(0, 0), (0, 100), (50, 100), (50, 101), (200, 101), (200, 0)]
    assert straighten(ring, jog_px=4) == [(0, 0), (0, 101), (200, 101), (200, 0)]


@pytest.mark.parametrize(("y0", "gaps"), [(203, 1), (207, 0)], ids=["overlap-70%", "overlap-30%"])
def test_collinear_needs_half_thickness_overlap(cfg, y0, gaps):
    # две горизонтальные стены толщиной 10 px, сдвинутые по y на 3 и на 7 px
    walls = [Box(150, 200, 250, 210), Box(300, y0, 400, y0 + 10)]
    assert len(find_gaps(walls, cfg.plan.gaps)) == gaps
