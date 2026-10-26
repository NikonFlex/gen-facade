"""Извлечение коттеджей BuildingNet (`data: Извлечение BuildingNet`, `data: Коттеджи из
BuildingNet`): дом из компонентов-коробок в единицах модели → план и фасады в метрах."""

import json
import math
import zipfile

import numpy
import pytest

from genfacade import config
from genfacade.datasets.buildingnet import extract, mesh
from genfacade.datasets.buildingnet.mesh import Component, Label
from genfacade.schema import ElementClass, OpeningKind, Source, Split
from genfacade.validate import errors, validate

CFG = config.load()
RULES = CFG.data.buildingnet
# Дверь 0,1 единицы высотой → 21 м на единицу (спека, сценарий «Масштаб по двери»).
M_PER_UNIT = RULES.door_height_m / 0.1
# Коробка 12 треугольниками: 6 граней по 2.
FACES = numpy.array([(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
                     (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)])


def box(label: Label, lo: tuple, hi: tuple) -> Component:
    """Коробка в осях OBJ (X, Y — вверх, Z)."""
    corners = numpy.array([(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1])
                           for z in (lo[2], hi[2])], dtype=float)
    return Component(label, corners, FACES)


def turned(parts: list[Component], degrees: float) -> list[Component]:
    a = math.radians(degrees)
    turn = numpy.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    return [p._replace(vertices=p.vertices @ turn.T) for p in parts]


# Дом 0,5 × 0,3 × 0,3 единицы — 10,5 × 6,3 м, карниз 6,3 м, два этажа. Дверь — на стене Z = 0,3
# (в плане y = −Z, сторона с нормалью (0, −1)), окно второго этажа из двух стёкол — на стене Z = 0.
WALLS = [box(Label.WALL, (0, 0, 0), (0.5, 0.3, 0.01)),
         box(Label.WALL, (0, 0, 0.29), (0.5, 0.3, 0.3)),
         box(Label.WALL, (0, 0, 0), (0.01, 0.3, 0.3)),
         box(Label.WALL, (0.49, 0, 0), (0.5, 0.3, 0.3))]
DOOR = box(Label.DOOR, (0.2, 0, 0.295), (0.25, 0.1, 0.305))
PANES = [box(Label.WINDOW, (0.1, 0.2, -0.005), (0.13, 0.26, 0.005)),
         box(Label.WINDOW, (0.125, 0.2, -0.005), (0.16, 0.26, 0.005))]
INSIDE = [box(Label.WALL, (0.25, 0, 0.01), (0.26, 0.3, 0.29)),       # перегородка
          box(Label.WALL, (-0.5, 0, -0.5), (0.9, 0.04, -0.49)),       # низкий забор
          box(Label.PLANT_TREE, (0.6, 0, 0.6), (0.7, 0.4, 0.7))]
HOUSE = WALLS + [DOOR, *PANES, *INSIDE]


@pytest.fixture(scope="module")
def sample():
    return extract.house("RESIDENTIALhouse_mesh0001", turned(HOUSE, 20), RULES)


def test_split_comes_from_the_official_list():
    """Часть примера — из официального разбиения BuildingNet (`data: Разбиение без утечек`):
    дом train в тест не попадает (gf#198)."""
    got = extract.house("RESIDENTIALhouse_mesh0001", turned(HOUSE, 20), RULES, Split.TRAIN)
    assert got.split is Split.TRAIN


def test_scale_by_door(sample):
    """Масштаб по двери: стороны дома в метрах, дверь — 2,1 м."""
    lengths = sorted(round(f.side.length_m, 2) for f in sample.sheet.facades)
    assert lengths == pytest.approx(sorted([0.5 * M_PER_UNIT, 0.3 * M_PER_UNIT] * 2), abs=0.05)
    door = next(e for f in sample.sheet.facades for e in f.elements if e.cls is ElementClass.DOOR)
    assert door.h_m == pytest.approx(RULES.door_height_m, abs=0.01)


def test_house_and_sides(sample):
    """Пример — тест BuildingNet, стороны с входом первой, карниз по стенам, этажи по высоте."""
    spec, first = sample.sheet.spec, sample.sheet.facades[0]
    assert (sample.source, sample.split) == (Source.BUILDINGNET, Split.TEST)
    assert spec.eaves_m == pytest.approx(0.3 * M_PER_UNIT, abs=0.05)
    assert spec.floors == round((spec.eaves_m - spec.plinth_m) / RULES.floor_height_m)
    assert first.side.has_entrance
    assert [o.kind for o in first.side.openings] == [OpeningKind.ENTRANCE]
    assert len(sample.plan.sides) == 4


def test_window_panes_merge(sample):
    """Окно из двух стёкол — один элемент на противоположной входу стороне, второй этаж; x — от
    левого края стены, если смотреть снаружи: у стены Z = 0 это её край X = 0,5."""
    windows = [(f.side.index, e) for f in sample.sheet.facades for e in f.elements
               if e.cls is ElementClass.WINDOW]
    assert len(windows) == 1
    side, w = windows[0]
    assert side == 2
    assert (w.x_m, w.w_m, w.y_m, w.floor) == pytest.approx(
        ((0.5 - 0.16) * M_PER_UNIT, 0.06 * M_PER_UNIT, 0.2 * M_PER_UNIT, 2), abs=0.05)


def test_valid_sheet(sample):
    assert errors(validate(sample.sheet, CFG.checks)) == []


def test_window_over_door_stays_out_of_plan():
    """Окно над дверью первого этажа налезает на неё по x: в плане — один разрыв стены, дверь,
    а окно остаётся на фасаде (gf#186) — лист без ошибок, проём плана на месте."""
    over = box(Label.WINDOW, (0.21, 0.11, 0.295), (0.24, 0.13, 0.305))
    got = extract.house("RESIDENTIALhouse_mesh0002", turned(HOUSE + [over], 20), RULES)
    front = got.sheet.facades[0]
    assert [o.kind for o in front.side.openings] == [OpeningKind.ENTRANCE]
    assert [(e.cls, e.floor) for e in front.elements if e.cls is ElementClass.WINDOW] == [
        (ElementClass.WINDOW, 1)]
    assert errors(validate(got.sheet, CFG.checks)) == []


def test_window_in_door_is_door_glass():
    """Стекло двери, размеченное окном, — часть двери, а не второй проём."""
    glass = box(Label.WINDOW, (0.21, 0.03, 0.296), (0.24, 0.09, 0.304))
    sample = extract.house("m", WALLS + [DOOR, glass], RULES)
    classes = [e.cls for f in sample.sheet.facades for e in f.elements]
    assert classes == [ElementClass.DOOR]


L_BLOCKS = [box(Label.WALL, (0, 0, 0), (0.5, 0.3, 0.15)),   # Г-дом: крыло 0,5 × 0,15
            box(Label.WALL, (0, 0, 0.15), (0.2, 0.3, 0.3))]  # и крыло 0,2 × 0,15 к нему
L_DOOR = box(Label.DOOR, (0.05, 0, 0.295), (0.1, 0.1, 0.305))


def test_l_shaped_house():
    """Г-образный дом (gf#198): у стороны две плоскости стен — контур в шесть сторон, план и лист
    собираются, валидатор доволен."""
    sample = extract.house("m", L_BLOCKS + [L_DOOR], RULES)
    assert len(sample.sheet.facades) == len(sample.plan.outline) == 6
    lengths = sorted(round(f.side.length_m / M_PER_UNIT, 2) for f in sample.sheet.facades)
    assert lengths == pytest.approx([0.15, 0.15, 0.2, 0.3, 0.3, 0.5], abs=0.01)
    assert errors(validate(sample.sheet, CFG.checks)) == []


def test_two_volumes_rejected():
    """Два отдельных объёма — не один дом: отказ с причиной."""
    apart = [box(Label.WALL, (0, 0, 0), (0.2, 0.3, 0.3)),
             box(Label.WALL, (0.4, 0, 0), (0.6, 0.3, 0.3))]
    with pytest.raises(extract.Rejected) as e:
        extract.house("m", apart + [L_DOOR], RULES)
    assert e.value.reason is extract.Reason.NOT_ORTHOGONAL


def test_side_without_wall_rejected(monkeypatch):
    """Сторона контура, у плоскости которой нет стены, — отказ с причиной, а не падение сборки."""
    facing = extract._facing
    monkeypatch.setattr(extract, "_facing", lambda w, parts, cfg: facing(w, parts, cfg)[:0]
                        if w.normal[0] < 0 else facing(w, parts, cfg))
    with pytest.raises(extract.Rejected) as e:
        extract.house("m", L_BLOCKS + [L_DOOR], RULES)
    assert e.value.reason is extract.Reason.NOT_ORTHOGONAL


def test_no_door():
    with pytest.raises(extract.Rejected) as e:
        extract.house("m", WALLS + PANES, RULES)
    assert e.value.reason is extract.Reason.NO_DOOR


def test_read_obj(tmp_path):
    """Объект OBJ — компонент со своей меткой; многоугольник режется веером на треугольники."""
    obj = tmp_path / "m.obj"
    obj.write_text("v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\n"
                   "o 0\nf 1//1 2//1 3//1 4//1\no 1\nf 1 2 5\n")
    archive = tmp_path / "labels.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("component_labels/m_label.json", json.dumps({"0": 1, "1": 2}))
    parts = mesh.read(obj, mesh.labels(archive, "m"))
    assert [(p.label, len(p.faces), len(p.vertices)) for p in parts] == [
        (Label.WALL, 2, 4), (Label.WINDOW, 1, 3)]
