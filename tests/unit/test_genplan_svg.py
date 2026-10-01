"""Разбор SVG GenPlan на простом доме (tests/fixtures/simple_house.svg, нарисован кодом GenPlan)."""

import pytest
from simple_house import LEAF

from genfacade.plan import genplan_svg
from genfacade.plan.genplan_svg import Box, PlanError, parse


def _swings(plan):
    return [(d.hinge, d.jamb) for d in plan.doors]


def test_simple_house_primitives(simple_svg):
    plan = parse(simple_svg())
    assert (plan.width, plan.height) == (1200, 700)
    assert len(plan.walls) == 9  # 10 чёрных <rect> минус створка входа
    assert plan.windows == [Box(250, 585, 370, 600), Box(100, 350, 115, 450),
                            Box(1085, 250, 1100, 400), Box(600, 100, 800, 115)]
    # створка открыта внутрь дома: петля и край разрыва — на внутренней грани нижней стены
    assert _swings(plan) == [((800, 585), (890, 585))]


@pytest.mark.parametrize(
    "wall",
    [Box(790, 400, 800, 585), Box(790, 495, 800, 585), Box(795, 400, 800, 585)],
    ids=["longer", "same-length", "leaf-thick-longer"],
)
def test_leaf_not_confused_with_wall_along_it(simple_svg, wall):
    # Внутренняя стена вдоль створки касается петли и конца створки; GenPlan такую дверь
    # допускает (can_create_door проверяет только пересечение). Стена должна остаться,
    # даже если она длиной с радиус дуги или толщиной со створку.
    w, h = wall.x1 - wall.x0, wall.y1 - wall.y0
    rect = f'<rect x="{wall.x0}" y="{wall.y0}" width="{w}" height="{h}" fill="#000000" />'
    plan = parse(simple_svg((LEAF, rect + "\n" + LEAF)))
    assert wall in plan.walls and len(plan.walls) == 10
    assert _swings(plan) == [((800, 585), (890, 585))]


@pytest.mark.parametrize(
    ("replacement", "reason"),
    [
        (('fill="#99ccff"', 'fill="#965032"'), "неизвестного цвета"),
        (("</svg>", '<line x1="0" y1="0" x2="1" y2="1" /></svg>'), "неожиданный элемент"),
        ((LEAF, LEAF.replace("/>", 'transform="rotate(90)" />')), "transform"),
        ((LEAF, ""), "без створки"),
        (('d="M890.0,585.0 A', 'd="M890.0,585.0 L'), "не дуга"),
        (('width="5" height="90"', 'width="0" height="90"'), "нулевого размера"),
        (("</svg>", ""), "не разбирается"),
        (('viewBox="0 0 1200 700"', 'viewBox="10 0 1200 700"'), "не от нуля"),
        ((' viewBox="0 0 1200 700"', ""), "нет viewBox"),
    ],
    ids=["color", "element", "transform", "no-leaf", "not-arc", "empty-rect", "xml",
         "viewbox-offset", "no-viewbox"],
)
def test_defects_rejected_with_reason(simple_svg, replacement, reason):
    with pytest.raises(PlanError, match=reason):
        parse(simple_svg(replacement))


def test_old_expat_refused(simple_svg, monkeypatch):
    monkeypatch.setattr(genplan_svg.pyexpat, "version_info", (2, 5, 0))
    with pytest.raises(PlanError, match="expat"):
        parse(simple_svg())
