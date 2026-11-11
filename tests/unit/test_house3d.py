"""Дом объёмом для смотрелки: стены по контуру, лицом наружу, фасад стороны — текстурой."""

import math

import pytest
from test_unfold import L_SIDES, sides_of

from genfacade.datasets.synthetic import build
from genfacade.render import hatch
from genfacade.render.house3d import house_3d
from genfacade.render.sheet_format import num
from genfacade.render.svg import element_fill, pen_for, sheet_svg
from genfacade.schema import (
    ElementClass,
    FacadeSheet,
    Roof,
    RoofKind,
    SideFacade,
    ZoneRole,
)
from genfacade.unfold import unfold


def _l_house(house: FacadeSheet) -> FacadeSheet:
    """Простой дом на Г-образном контуре из test_unfold.py: шесть стен без элементов."""
    facades = [SideFacade(side=s) for s in sides_of(L_SIDES)]
    return unfold(house.model_copy(update={"facades": facades}))


def _flat_roofed(sheet: FacadeSheet) -> FacadeSheet:
    """Дом под плоской крышей: карниз у него — выступ (под скатом — полоса на стене, gf#320)."""
    return sheet.model_copy(update={"spec": sheet.spec.model_copy(
        update={"roof": Roof(kind=RoofKind.FLAT)}), "roofs": [], "wall_gables": []})


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


def test_wall_outline_follows_its_silhouette(sheet, cfg):
    """Обводка стены — по силуэту (gf#431): у стены со ступенью рамка во всю высоту висела бы
    над нижней частью; силуэт у стены есть — он и идёт в выгрузку, высота — его верх."""
    for wall, f in zip(house_3d(sheet, cfg)["walls"], sheet.facades, strict=True):
        assert f.silhouette and wall["outline"] == f.silhouette
        assert wall["height_m"] == pytest.approx(max(y for _, y in f.silhouette))


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
    sheet = next(s for s in (_flat_roofed(build.sample(k, cfg).sheet) for k in range(20))
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
    sheet = next(s for s in (_flat_roofed(build.sample(k, cfg).sheet) for k in range(20))
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


def _rich_houses(cfg) -> list[FacadeSheet]:
    """Синтетические дома, где есть и крыльцо, и козырёк, и подоконник, и карниз, — с видами
    козырька и подоконника на любой вкус."""
    need = {ElementClass.PORCH, ElementClass.CANOPY, ElementClass.SILL, ElementClass.CORNICE}
    found = [s for s in (_flat_roofed(build.sample(k, cfg).sheet) for k in range(120))
             if need <= {e.cls for f in s.facades for e in f.elements}]
    assert {s.spec.trim.canopy for s in found} >= {*cfg.derive.canopy}
    assert {s.spec.trim.sill for s in found} >= {*cfg.derive.sill}
    return found


@pytest.mark.slow
def test_relief_tells_its_class_and_kind(cfg):
    """gf#305: форму выступа строит просмотр по его классу и форме — `house_3d` отдаёт класс
    (элемент) или роль (зона), а у козырька и подоконника — форма записи вида дома (derive.toml)."""
    kinds = {ElementClass.CANOPY: "canopy", ElementClass.SILL: "sill"}
    seen = set()
    for sheet in _rich_houses(cfg):
        for wall, facade in zip(house_3d(sheet, cfg)["walls"], sheet.facades, strict=True):
            raised = [e for e in facade.elements if e.cls in cfg.viewer.house3d.relief_cls]
            got = [b for b in wall["relief"] if b["cls"] is not None]
            assert [b["cls"] for b in got] == [e.cls for e in raised]
            assert [b["role"] for b in wall["relief"] if b["cls"] is None] == [
                z.role for z in facade.zones if z.role in cfg.viewer.house3d.relief_role]
            for b in got:
                kind = getattr(sheet.spec.trim, kinds[b["cls"]]) if b["cls"] in kinds else None
                want = cfg.derive.look(kinds[b["cls"]], kind).shape if kind else None
                assert b["shape"] == want, b["cls"]
                seen.add((b["cls"], b["shape"]))
    assert {(ElementClass.CANOPY, k.shape) for k in cfg.derive.canopy.values()} <= seen
    assert {(ElementClass.SILL, k.shape) for k in cfg.derive.sill.values()} <= seen
    assert {c for c, _ in seen} >= {ElementClass.CORNICE, ElementClass.PORCH}


def _porch_of_height(cfg, height_m: float) -> dict:
    """Крыльцо дома с высотой `height_m`, как его отдаёт `house_3d`."""
    sheet = _rich_houses(cfg)[0]
    facades = [f.model_copy(update={"elements": [
        e.model_copy(update={"h_m": height_m}) if e.cls is ElementClass.PORCH else e
        for e in f.elements]}) for f in sheet.facades]
    walls = house_3d(sheet.model_copy(update={"facades": facades}), cfg)["walls"]
    return next(b for w in walls for b in w["relief"] if b["cls"] is ElementClass.PORCH)


@pytest.mark.slow
@pytest.mark.parametrize(("height_m", "steps"), [(0.61, 4), (7 * 0.17, 7), (0.17, 1), (0.18, 2)])
def test_porch_steps_from_height(cfg, height_m, steps):
    """Число ступеней — высота крыльца, поделённая на высоту ступени (0,17 м), вверх: 0,61 м —
    четыре; ровно семь ступеней (7 × 0,17 = 1,1900000000000002 в двоичной дроби) не становятся
    восемью."""
    assert cfg.viewer.house3d.riser_m == 0.17
    assert _porch_of_height(cfg, height_m)["steps"] == steps


def test_corner_is_convex_or_not(sheet, cfg):
    """Выпуклость левого угла стены — от неё зависит стык карнизов на углу: у прямоугольника все
    углы выпуклые, у Г-образного дома внутренний угол — левый у четвёртой стороны (индекс 3)."""
    got = [w["convex_left"] for w in house_3d(sheet, cfg)["walls"]]
    assert got == ([True] * 4 if len(got) == 4 else [True, True, True, False, True, True])


def test_cornice_under_slope_is_a_band_flat_roof_covers_it(cfg, rect_cfg):
    """gf#320, хозяин 07.11: «карниз выпирает за крышу». Под скатом карниз — полоса на стене под
    свесом, а не выступ сквозь кровлю; у плоской крыши плита шире плана на вынос карниза."""
    sheet = next(s for s in (build.sample(k, rect_cfg).sheet for k in range(20))
                 if any(e.cls is ElementClass.CORNICE for f in s.facades for e in f.elements))
    gable = sheet.model_copy(update={"spec": sheet.spec.model_copy(update={
        "roof": cfg.models.spec.roof_shape.roof(RoofKind.GABLE, "roof")})})
    for wall, facade in zip(house_3d(gable, cfg)["walls"], gable.facades, strict=True):
        assert all(b["cls"] is not ElementClass.CORNICE for b in wall["relief"])
        for e in facade.elements:
            if e.cls is ElementClass.CORNICE:
                assert f'data-id="{e.id}"' in wall["svg"]
    flat = house_3d(_flat_roofed(sheet), cfg)
    out = cfg.viewer.house3d.relief_cls[ElementClass.CORNICE]
    xs = [x for x, _ in flat["corners"]]
    assert min(x for x, _ in flat["roof"]["flat"]) == pytest.approx(min(xs) - out)
    assert max(x for x, _ in flat["roof"]["flat"]) == pytest.approx(max(xs) + out)


def _gabled(sheet: FacadeSheet, cfg, roof_kind: str, main_kind: str = "plaster") -> FacadeSheet:
    """Дом под двускатной кровлей: кровля и стена — материалы данного вида, остальное как было."""
    kinds = {"roof": roof_kind, "main": main_kind}
    palette = [m.model_copy(update={"kind": kinds.get(m.id, m.kind), "color": None})
               if m.id in kinds else m for m in sheet.spec.materials]
    spec = sheet.spec.model_copy(update={
        "materials": palette, "roof": cfg.models.spec.roof_shape.roof(RoofKind.GABLE, "roof")})
    return sheet.model_copy(update={"spec": spec})


@pytest.mark.parametrize("kind", ["metal_tile", "shingle_roof", "ondulin", "metal_roof"])
def test_roof_comes_with_its_pattern_swatch(house, cfg, kind):
    """gf#353, хозяин 08.11: «красивые материалы, а в 3D я их не вижу». Кровля в 3D — рисунком
    вида кровли: дом отдаёт id материала кровли и ячейку рисунка (SVG и размер в метрах из
    `[patterns]`) — выкладывает её просмотр по скату."""
    data = house_3d(_gabled(house, cfg, kind), cfg)
    assert data["roof"]["material"] == "roof"
    swatch = data["swatches"]["roof"]
    tile = hatch.tile_m(cfg.library.patterns[kind])
    assert (swatch["width_m"], swatch["height_m"]) == tile
    assert f'id="hatch-{kind}-' in swatch["svg"]


def test_no_pattern_no_swatch_wall_above_eaves_keeps_the_wall_material(house, cfg):
    """Штукатурка и бетон без рисунка — ячейки нет, просмотр красит цветом; стена над карнизом
    (щипец) — материал main с рисунком, как стена под карнизом."""
    plain = house_3d(_gabled(house, cfg, "tile_roof"), cfg)
    assert plain["roof"]["material"] == "roof" and "roof" not in plain["swatches"]
    brick = house_3d(_gabled(house, cfg, "tile_roof", "brick_1_5"), cfg)
    assert brick["roof"]["wall_material"] == "main" and "main" in brick["swatches"]


def test_relief_of_patterned_material_knows_its_swatch(cfg):
    """Цоколь из камня — выступ с материалом, у которого рисунок есть: просмотр красит его
    ячейкой. Элемент, залитый цветом класса (у окна рисунка нет), материала не называет."""
    sheet = next(s for s in (build.sample(k, cfg).sheet for k in range(20))
                 if any(z.role is ZoneRole.PLINTH for f in s.facades for z in f.zones))
    plinth = next(z.material for f in sheet.facades for z in f.zones if z.role is ZoneRole.PLINTH)
    palette = [m.model_copy(update={"kind": "stone"}) if m.id == plinth else m
               for m in sheet.spec.materials]
    sheet = sheet.model_copy(update={"spec": sheet.spec.model_copy(update={"materials": palette})})
    data = house_3d(sheet, cfg)
    reliefs = [r for w in data["walls"] for r in w["relief"]]
    zones = [r for r in reliefs if r["role"] is ZoneRole.PLINTH]
    assert zones and all(r["material"] == plinth for r in zones)
    assert plinth in data["swatches"]
    assert all(r["material"] in data["swatches"] for r in zones)


def test_roof_data_carries_the_sheet_thickness(house, cfg):
    """3D берёт толщину кровли из настроек листа (gf#447): и для скатов, и для плоской плиты —
    в JS своей константы нет."""
    gabled = house.model_copy(update={"spec": house.spec.model_copy(update={
        "roof": cfg.models.spec.roof_shape.roof(RoofKind.GABLE, "roof")})})
    for sheet in (gabled, _flat_roofed(house)):
        assert house_3d(sheet, cfg)["roof"]["thickness_m"] == cfg.sheet.roof.thickness_m == 0.2
