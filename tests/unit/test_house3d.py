"""Дом объёмом для смотрелки: стены по контуру, лицом наружу, фасад стороны — текстурой."""

import math

import pytest
from test_unfold import L_SIDES, sides_of

from genfacade.datasets.synthetic import build
from genfacade.render.house3d import house_3d
from genfacade.render.sheet_format import num
from genfacade.render.svg import element_fill, pen_for, sheet_svg
from genfacade.schema import ElementClass, FacadeSheet, SideFacade, ZoneRole
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
    """SVG стены — ровно стена (длина × карниз), с элементами листа, кроме выступов, без
    подписей и осей."""
    data = house_3d(house, cfg)
    look = cfg.viewer.house3d
    for wall, facade in zip(data["walls"], house.facades, strict=True):
        assert f'viewBox="0 0 {num(wall["length_m"])} {num(data["eaves_m"])}"' in wall["svg"]
        flat = [e for e in facade.elements if e.cls not in look.relief_cls]
        assert all(f'data-id="{e.id}"' in wall["svg"] for e in flat)
        assert "<text" not in wall["svg"]


def test_relief_is_not_drawn_twice(cfg):
    """gf#277: подоконник, карниз, козырёк и цоколь стоят выступом, а на текстуре стены их нет —
    иначе под углом видны оба со сдвигом. На листе фасадов они остаются."""
    look = cfg.viewer.house3d
    sheet = next(s for s in (build.sample(k, cfg).sheet for k in range(20))
                 if any(e.cls in look.relief_cls for f in s.facades for e in f.elements)
                 and any(z.role in look.relief_role for f in s.facades for z in f.zones))
    sheet_svg_text = sheet_svg(sheet, cfg)
    for wall, facade in zip(house_3d(sheet, cfg)["walls"], sheet.facades, strict=True):
        raised = [e for e in facade.elements if e.cls in look.relief_cls]
        zones = [z for z in facade.zones if z.role in look.relief_role]
        assert len(wall["relief"]) == len(raised) + len(zones)
        for e in raised:
            assert f'data-id="{e.id}"' not in wall["svg"]
            assert f'data-id="{e.id}"' in sheet_svg_text
        for z in zones:
            assert f'data-role="{z.role}"' not in wall["svg"]
    assert all(f'data-role="{z.role}"' in sheet_svg_text
               for f in sheet.facades for z in f.zones if z.role in look.relief_role)


def test_plinth_and_cornice_stand_out(cfg):
    """Хозяин 03.11: цоколь и карниз — объёмом. У стены синтетики с карнизом и цоколем выступы —
    рамкой того же элемента или зоны, глубиной из `[house3d]` и цветом листа."""
    sheet = next(s for s in (build.sample(k, cfg).sheet for k in range(20))
                 if any(e.cls is ElementClass.CORNICE for f in s.facades for e in f.elements)
                 and any(z.role is ZoneRole.PLINTH for f in s.facades for z in f.zones))
    look, pen = cfg.viewer.house3d, pen_for(sheet, cfg)
    for wall, facade in zip(house_3d(sheet, cfg)["walls"], sheet.facades, strict=True):
        boxes = {(b["x0"], b["y0"], b["x1"], b["y1"]): b for b in wall["relief"]}
        for e in facade.elements:
            if e.cls is ElementClass.CORNICE:
                got = boxes[(e.x_m, e.y_m, e.x_m + e.w_m, e.y_m + e.h_m)]
                assert got["depth"] == look.relief_cls[e.cls]
                assert got["color"] == element_fill(e, pen)
        plinths = [z for z in facade.zones if z.role is ZoneRole.PLINTH]
        raised = [e for e in facade.elements if e.cls in look.relief_cls]
        assert len(wall["relief"]) == len(plinths) + len(raised)
        deep = look.relief_role[ZoneRole.PLINTH]
        assert sum(b["depth"] == deep for b in wall["relief"]) >= len(plinths)
