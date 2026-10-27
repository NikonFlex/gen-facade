"""Шаг 3: развёртка — прямоугольники стен; крыша пока только плоская (хозяин 01.10)."""

import pytest

from genfacade.schema import Side
from genfacade.unfold import plan_corners


def assert_corners(corners, expected) -> None:
    # pytest 9.2 не сравнивает approx со списком пар: сравниваем по углу.
    assert corners == [pytest.approx(c) for c in expected]


def test_unfold_is_walls_only(lay_out):
    """У каждой стороны — прямоугольник: длина из плана, высота до карниза из HouseSpec."""
    sheet = lay_out()
    for f in sheet.facades:
        length, eaves = f.side.length_m, sheet.spec.eaves_m
        assert f.silhouette == [(0.0, 0.0), (length, 0.0), (length, eaves), (0.0, eaves)]


def test_corners_of_rectangle(lay_out):
    sheet = lay_out()
    corners = plan_corners([f.side for f in sheet.facades])
    assert_corners(corners, [(0.0, 0.0), (-10.0, 0.0), (-10.0, 5.0), (0.0, 5.0)])


def test_counterclockwise_sides_rejected():
    sides = [
        Side(index=0, length_m=10, orientation=(0, -1)),
        Side(index=1, length_m=8, orientation=(1, 0)),  # по часовой после юга — запад
        Side(index=2, length_m=10, orientation=(0, 1)),
        Side(index=3, length_m=8, orientation=(-1, 0)),
    ]
    with pytest.raises(ValueError, match="по часовой"):
        plan_corners(sides)


# Г-образный дом по часовой от южной стороны (нормаль вниз): юг 10, запад 8, север 4, восток 4,
# внутренний угол, север 6, восток 4 — шесть сторон (gf#199).
L_SIDES = [((0, -1), 10), ((-1, 0), 8), ((0, 1), 4), ((1, 0), 4), ((0, 1), 6), ((1, 0), 4)]


def sides_of(spec) -> list[Side]:
    return [Side(index=k, length_m=n, orientation=o) for k, (o, n) in enumerate(spec)]


def test_corners_of_l_shape():
    """Ортогональный контур с внутренним углом — шесть углов по часовой (`data: Ступени данных`)."""
    corners = plan_corners(sides_of(L_SIDES))
    assert_corners(corners, [(0, 0), (-10, 0), (-10, 8), (-6, 8), (-6, 4), (0, 4)])


@pytest.mark.parametrize(("spec", "reason"), [
    (L_SIDES[:-1] + [((1, 0), 3)], "не замкнулся"),
    (L_SIDES[:2] + [((0.6, 0.8), 4)] + L_SIDES[3:], "±90"),
])
def test_broken_contour_rejected(spec, reason):
    with pytest.raises(ValueError, match=reason):
        plan_corners(sides_of(spec))
