"""Разбор SVG GenPlan: примитивы из примера и из дверей, нарисованных кодом GenPlan."""

from pathlib import Path

import pytest

from genfacade.plan import genplan_svg
from genfacade.plan.genplan_svg import Box, PlanError, parse

ROOT = Path(__file__).parents[2]
EXAMPLE = ROOT / "materials" / "genplan-plan-example.svg"  # в git нет (gf#20) — только локально
DOORS = ROOT / "tests" / "fixtures" / "genplan"
HOUSE = DOORS / "house.svg"  # наш дом, окна и двери нарисовал decorator GenPlan
# Разрывы дверей (петля, другой край) — как заданы в tests/fixtures/genplan/make_fixtures.py
DOOR_GAPS = {
    "door_top": [((250, 100), (340, 100))],  # створка BOTTOM, наружу
    "door_left": [((100, 250), (100, 340))],  # RIGHT, наружу
    "door_edge": [((150, 15), (240, 15)), ((15, 150), (15, 240))],  # UP и LEFT, внутрь
}
WALLS_LEFT = {"door_top": 5, "door_left": 5, "door_edge": 6}


def _swings(plan):
    return [(d.hinge, d.jamb) for d in plan.doors]


def test_house_primitives():
    plan = parse(HOUSE)
    assert (plan.width, plan.height) == (600, 600)
    assert len(plan.walls) == 10  # 11 чёрных <rect> минус створка входа
    # второе окно — ложное окно GenPlan поперёк комнаты; разбор его честно читает,
    # отбрасывает препроцессор (test_plan)
    assert plan.windows == [Box(250, 150, 400, 165), Box(100, 165, 250, 310),
                            Box(100, 330, 115, 420)]
    assert _swings(plan) == [((100, 200), (100, 290))]


@pytest.mark.skipif(not EXAMPLE.exists(), reason="materials/*.svg в git нет (gf#20)")
def test_example_primitives():
    plan = parse(EXAMPLE)
    assert (plan.width, plan.height) == (1024, 1024)
    assert len(plan.walls) == 12  # 13 чёрных <rect> минус створка входа
    assert plan.windows == [Box(501, 300, 784, 317), Box(187, 593, 203, 781)]
    assert _swings(plan) == [((187, 368), (187, 486))]


@pytest.mark.parametrize("name", sorted(DOOR_GAPS))
def test_doors_in_every_leaf_position(name):
    plan = parse(DOORS / f"{name}.svg")
    assert _swings(plan) == [
        (pytest.approx(h, abs=genplan_svg.TOL_PX), pytest.approx(j, abs=genplan_svg.TOL_PX))
        for h, j in DOOR_GAPS[name]
    ]
    # створки, в том числе UP без fill, из стен убраны
    assert len(plan.walls) == WALLS_LEFT[name]


@pytest.mark.parametrize(
    "wall",
    [Box(15, 140, 200, 150), Box(15, 140, 105, 150), Box(15, 145, 200, 150)],
    ids=["longer", "same-length", "leaf-thick-longer"],
)
def test_leaf_not_confused_with_wall_along_it(wall):
    # Внутренняя стена вдоль створки LEFT касается петли и конца створки; GenPlan такую
    # дверь допускает (can_create_door проверяет только пересечение). Стена должна остаться,
    # даже если она длиной с радиус дуги или толщиной со створку.
    w, h = wall.x1 - wall.x0, wall.y1 - wall.y0
    rect = f'<rect x="{wall.x0}" y="{wall.y0}" width="{w}" height="{h}" fill="#000000" />'
    text = (DOORS / "door_edge.svg").read_text().replace("<rect", rect + "\n<rect", 1)
    plan = parse(text)
    assert wall in plan.walls
    assert len(plan.walls) == WALLS_LEFT["door_edge"] + 1


def test_parse_accepts_text():
    assert parse(HOUSE.read_text()) == parse(HOUSE)


def _broken(old: str, new: str) -> str:
    text = HOUSE.read_text()
    assert old in text
    return text.replace(old, new, 1)


LEAF = '<rect x="10" y="200" width="90" height="5" fill="#000000" />'


@pytest.mark.parametrize(
    ("svg", "reason"),
    [
        (_broken('fill="#99ccff"', 'fill="#965032"'), "неизвестного цвета"),
        (_broken("</svg>", '<line x1="0" y1="0" x2="1" y2="1" /></svg>'), "неожиданный элемент"),
        (_broken(LEAF, LEAF.replace("/>", 'transform="rotate(90)" />')), "transform"),
        (_broken(LEAF, ""), "без створки"),
        (_broken('d="M100.0,290.0 A', 'd="M100.0,290.0 L'), "не дуга"),
        (_broken('width="90" height="5"', 'width="0" height="5"'), "нулевого размера"),
        (_broken("</svg>", ""), "не разбирается"),
        (_broken('viewBox="0 0 600 600"', 'viewBox="10 0 600 600"'), "не от нуля"),
        (_broken(' viewBox="0 0 600 600"', ""), "нет viewBox"),
    ],
    ids=["color", "element", "transform", "no-leaf", "not-arc", "empty-rect", "xml",
         "viewbox-offset", "no-viewbox"],
)
def test_defects_rejected_with_reason(svg, reason):
    with pytest.raises(PlanError, match=reason):
        parse(svg)


def test_old_expat_refused(monkeypatch):
    monkeypatch.setattr(genplan_svg.pyexpat, "version_info", (2, 5, 0))
    with pytest.raises(PlanError, match="expat"):
        parse(HOUSE)
