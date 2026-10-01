"""Шаг 3: развёртка — прямоугольники стен; крыша пока только плоская (хозяин 01.10)."""

import pytest

from genfacade.schema import Side
from genfacade.unfold import plan_corners


def test_unfold_is_walls_only(lay_out):
    """У каждой стороны — прямоугольник: длина из плана, высота до карниза из HouseSpec."""
    sheet = lay_out()
    for f in sheet.facades:
        length, eaves = f.side.length_m, sheet.spec.eaves_m
        assert f.silhouette == [(0.0, 0.0), (length, 0.0), (length, eaves), (0.0, eaves)]


def test_corners_of_rectangle(lay_out):
    sheet = lay_out()
    corners = plan_corners([f.side for f in sheet.facades])
    assert corners == pytest.approx([(0.0, 0.0), (-10.0, 0.0), (-10.0, 5.0), (0.0, 5.0)])


def test_counterclockwise_sides_rejected():
    sides = [
        Side(index=0, length_m=10, orientation=(0, -1)),
        Side(index=1, length_m=8, orientation=(1, 0)),  # по часовой после юга — запад
        Side(index=2, length_m=10, orientation=(0, 1)),
        Side(index=3, length_m=8, orientation=(-1, 0)),
    ]
    with pytest.raises(ValueError, match="по часовой"):
        plan_corners(sides)
