"""Дом объёмом для смотрелки: стены по контуру, лицом наружу, фасад стороны — текстурой."""

import math

import pytest
from test_unfold import L_SIDES, sides_of

from genfacade.render.house3d import house_3d
from genfacade.render.sheet_format import num
from genfacade.schema import FacadeSheet, SideFacade
from genfacade.unfold import unfold


def _l_house(house: FacadeSheet) -> FacadeSheet:
    """Простой дом на Г-образном контуре из test_unfold.py: шесть стен без элементов."""
    facades = [SideFacade(side=s) for s in sides_of(L_SIDES)]
    return unfold(house.model_copy(update={"facades": facades}))


@pytest.fixture(params=["rectangle", "l-shape"])
def sheet(request, house) -> FacadeSheet:
    return house if request.param == "rectangle" else _l_house(house)


def test_walls_close_the_contour(sheet, cfg):
    """Правый край стены — левый край предыдущей: стены идут без щелей по обходу контура."""
    walls = house_3d(sheet, cfg)["walls"]
    assert len(walls) == len(sheet.facades)
    for prev, wall in zip(walls[-1:] + walls[:-1], walls, strict=True):
        assert wall["right"] == pytest.approx(prev["left"])
        assert math.dist(wall["left"], wall["right"]) == pytest.approx(wall["length_m"])


def test_wall_faces_outward_left_to_right(sheet, cfg):
    """Снаружи (смотрим против нормали) левый край стены — слева: x фасада идёт от него."""
    for wall in house_3d(sheet, cfg)["walls"]:
        (lx, ly), (rx, ry), (nx, ny) = wall["left"], wall["right"], wall["normal"]
        # Для смотрящего против нормали левая рука — нормаль, повёрнутая на −90°.
        assert (lx - rx) * ny + (ly - ry) * (-nx) == pytest.approx(wall["length_m"])


def test_wall_texture_is_the_facade(house, cfg):
    """SVG стены — ровно стена (длина × карниз), с элементами листа, без подписей и осей."""
    data = house_3d(house, cfg)
    for wall, facade in zip(data["walls"], house.facades, strict=True):
        assert f'viewBox="0 0 {num(wall["length_m"])} {num(data["eaves_m"])}"' in wall["svg"]
        assert all(f'data-id="{e.id}"' in wall["svg"] for e in facade.elements)
        assert "<text" not in wall["svg"]
