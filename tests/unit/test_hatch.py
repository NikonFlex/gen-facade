"""Рисунок материала на листе (gf#304, `facade: Рисунок материала`): зоны и элементы из
кирпича, обшивки, дерева, камня заливаются SVG-паттерном из `<defs>`, штукатурка и бетон —
цветом."""

import re
from xml.etree import ElementTree

import pytest
from pydantic import ValidationError

from genfacade import config
from genfacade.render import hatch
from genfacade.render.house3d import house_3d
from genfacade.render.sheet_format import ID, MATERIAL, ROLE
from genfacade.render.svg import palette_colors, sheet_svg
from genfacade.schema import Element, ElementClass, FacadeSheet, ZoneRole

URL = re.compile(r"url\(#([^)]+)\)")


def _with_kind(house: FacadeSheet, material: str, kind: str) -> FacadeSheet:
    sheet = house.model_copy(deep=True)
    next(m for m in sheet.spec.materials if m.id == material).kind = kind
    return sheet


def _root(svg: str) -> ElementTree.Element:
    return ElementTree.fromstring(svg)


def _zone_fills(root: ElementTree.Element, material: str) -> list[str]:
    return [p.get("fill") for p in root.iterfind(".//{*}polygon")
            if p.get(ROLE) is not None and p.get(MATERIAL) == material]


def _patterns(root: ElementTree.Element) -> dict[str, ElementTree.Element]:
    return {p.get("id"): p for p in root.iterfind(".//{*}pattern")}


def _brick_pattern(house: FacadeSheet, cfg: config.Config) -> ElementTree.Element:
    """Паттерн кирпича с листа дома, у которого цоколь из кирпича."""
    root = _root(sheet_svg(_with_kind(house, "plinth", "brick"), cfg))
    return next(p for i, p in _patterns(root).items() if i.startswith("hatch-brick"))


def _horizontal_ys(pattern: ElementTree.Element) -> list[float]:
    """Высоты горизонтальных швов паттерна: отрезки пути `M x1,y L x2,y` с разными x."""
    segments = re.findall(r"M([\d.]+),([\d.]+)L([\d.]+),([\d.]+)", pattern.find("{*}path").get("d"))
    return sorted(float(y1) for x1, y1, x2, y2 in segments if y1 == y2 and x1 != x2)


def test_brick_zone_is_filled_with_pattern_plaster_with_color(house, cfg):
    """У зоны вида brick — заливка рисунком из <defs>, у штукатурки и бетона — сплошная."""
    sheet = _with_kind(house, "plinth", "brick")
    root = _root(sheet_svg(sheet, cfg))
    patterns = _patterns(root)
    plinth = _zone_fills(root, "plinth")
    assert plinth and all(URL.fullmatch(f) and URL.fullmatch(f).group(1) in patterns
                          for f in plinth)
    assert set(_zone_fills(root, "main")) == {palette_colors(sheet.spec, cfg)["main"]}
    # штукатурка без рисунка: паттерна у неё нет и в <defs>
    assert not any(i.startswith("hatch-plaster") for i in patterns)


def test_brick_course_pitch_is_75_mm(house, cfg):
    """Кладка 250 × 65 мм со швом 10 мм: ряд — 0,075 м по высоте, в рисунке два ряда."""
    pattern = _brick_pattern(house, cfg)
    ys = _horizontal_ys(pattern)
    assert len(ys) == 2 and ys[1] - ys[0] == pytest.approx(0.075)
    assert float(pattern.get("height")) == pytest.approx(0.15)
    assert pattern.get("patternUnits") == "userSpaceOnUse"


def test_pattern_declared_once_per_sheet(house, cfg):
    """Зон кирпича на листе много, паттерн — один на пару вид × цвет."""
    sheet = _with_kind(house, "main", "brick")
    root = _root(sheet_svg(sheet, cfg))
    zones = _zone_fills(root, "main")
    assert len(zones) > 1 and len(set(zones)) == 1
    ids = [p.get("id") for p in root.iterfind(".//{*}pattern")]
    assert len(ids) == len(set(ids))
    assert sum(i.startswith("hatch-brick") for i in ids) == 1
    # каждая ссылка на рисунок ведёт в <defs>
    used = {m.group(1) for m in URL.finditer(sheet_svg(sheet, cfg))}
    assert used <= set(ids)


def test_same_kind_other_color_is_other_pattern(house, cfg):
    """Цвет линий считается из цвета материала: кирпич другого цвета — свой паттерн."""
    sheet = _with_kind(house, "main", "brick")
    next(m for m in sheet.spec.materials if m.id == "plinth").kind = "brick"
    next(m for m in sheet.spec.materials if m.id == "plinth").color = "#404040"
    ids = _patterns(_root(sheet_svg(sheet, cfg)))
    assert sum(i.startswith("hatch-brick") for i in ids) == 2


def test_lines_are_darker_than_material(house, cfg):
    """Линии — тот же цвет материала, темнее на pattern_darken; фон паттерна — цвет материала."""
    pattern = _brick_pattern(house, cfg)
    color = cfg.library.kinds["brick"]
    assert pattern.find("{*}rect").get("fill") == color
    assert pattern.find("{*}path").get("stroke") == hatch.darken(color, cfg.library.pattern_darken)
    assert hatch.darken("#8c4a3a", 0.35) == "#5b3026"
    assert hatch.darken("#ffffff", 0.0) == "#ffffff"


def test_color_not_hex_cannot_be_darkened():
    with pytest.raises(ValueError, match="rebeccapurple"):
        hatch.darken("rebeccapurple", 0.35)


def _tile(cfg, kind: str) -> ElementTree.Element:
    return hatch.pattern(kind, cfg.library.patterns[kind], cfg.library.kinds[kind],
                         cfg.library.pattern_darken)


def test_vertical_pattern_is_the_rotated_horizontal_one(cfg):
    """Фальц кровли — те же ряды, повёрнутые: швы вертикальные, ячейка 0,5 × 0,5 м."""
    tile = _tile(cfg, "metal_roof")
    d = tile.find("{*}path").get("d")
    xs = re.findall(r"M([\d.]+),([\d.]+)L([\d.]+),([\d.]+)", d)
    assert xs and all(x1 == x2 and y1 != y2 for x1, y1, x2, y2 in xs)
    assert (tile.get("width"), tile.get("height")) == ("0.5", "0.5")


def test_siding_pattern_has_lap_groove(cfg):
    """Обшивка — горизонтальные доски в 150 мм, у каждого шва вторая линия нахлёста."""
    look = cfg.library.patterns["siding"]
    ys = _horizontal_ys(_tile(cfg, "siding"))
    assert ys == pytest.approx([look.line_m / 2, look.line_m / 2 + look.groove_m])
    assert float(_tile(cfg, "siding").get("height")) == pytest.approx(0.15)


def test_element_from_material_is_hatched_blind_and_window_are_not(house, cfg):
    """Карниз из дерева — рисунком; ставню (рисует себя линиями) и окно (стекло) — цветом."""
    sheet = _with_kind(house, "accent", "wood")
    facade = sheet.facades[0]
    boxes = {cls: Element(id=f"x-{cls}", cls=cls, x_m=0.0, y_m=1.0, w_m=1.0, h_m=0.3,
                          material="accent")
             for cls in (ElementClass.CORNICE, ElementClass.BLIND, ElementClass.WINDOW)}
    facade.elements = [*facade.elements, *boxes.values()]
    root = _root(sheet_svg(sheet, cfg))
    fills = {r.get(ID): r.get("fill") for r in root.iterfind(".//{*}rect") if r.get(ID)}
    assert URL.fullmatch(fills[boxes[ElementClass.CORNICE].id])
    assert fills[boxes[ElementClass.BLIND].id] == palette_colors(sheet.spec, cfg)["accent"]
    assert fills[boxes[ElementClass.WINDOW].id] == cfg.library.fill.glass


def test_wall_texture_for_3d_carries_its_patterns(house, cfg):
    """Текстура стены в 3D — тот же SVG: паттерны в <defs> самой стены, ссылки не висят."""
    sheet = _with_kind(house, "main", "siding")
    for wall in house_3d(sheet, cfg)["walls"]:
        root = _root(wall["svg"])
        ids = set(_patterns(root))
        used = {m.group(1) for m in URL.finditer(wall["svg"])}
        assert used and used <= ids


def test_pattern_does_not_bloat_the_sheet(house, cfg):
    """Датчик gf#304: рисунок не раздувает лист больше чем вдвое — и на доме с кирпичом,
    обшивкой и деревом сразу."""
    plain = cfg.model_copy(update={"library": cfg.library.model_copy(update={"patterns": {}})})
    sheet = _with_kind(_with_kind(house, "main", "siding"), "plinth", "brick")
    assert len(sheet_svg(sheet, cfg)) < 2 * len(sheet_svg(sheet, plain))


def test_pattern_of_unknown_kind_rejected(tmp_path):
    (tmp_path / "library.toml").write_text(
        "[patterns]\nunobtainium = { vertical = false, line_m = 0.01, groove_m = 0.0,"
        " width_m = 0.2, courses = [{ h_m = 0.1, joints_m = [] }] }\n")
    with pytest.raises(ValidationError, match="unobtainium"):
        config.load(tmp_path)


def test_zone_roles_are_all_hatched(house, cfg):
    """Рисунок — у зоны любой роли: у цоколя и у отделки основной стены одинаково."""
    sheet = _with_kind(_with_kind(house, "main", "siding"), "plinth", "brick")
    root = _root(sheet_svg(sheet, cfg))
    hatched = [p for p in root.iterfind(".//{*}polygon") if URL.fullmatch(p.get("fill", ""))]
    roles = {p.get(ROLE) for p in hatched}
    assert {ZoneRole.MAIN, ZoneRole.PLINTH} <= roles


def test_new_kinds_have_default_color_and_pattern(cfg):
    """Бревно, доска с планкой и клинкерная плитка — виды библиотеки с цветом и рисунком."""
    for kind in ("log", "board_batten", "clinker"):
        assert hatch.HEX.fullmatch(cfg.library.kinds[kind]) and kind in cfg.library.patterns


def test_plaster_concrete_and_metal_stay_solid(cfg):
    assert not {"plaster", "concrete", "metal"} & cfg.library.patterns.keys()


@pytest.mark.parametrize("kind", config.load().library.patterns)
def test_every_pattern_draws_inside_its_cell(house, cfg, kind):
    """Швы любого рисунка лежат внутри ячейки паттерна, а лист с ним — разбираемый XML."""
    look = cfg.library.patterns[kind]
    assert all(0 <= x < look.width_m for c in look.courses for x in c.joints_m)
    root = _root(sheet_svg(_with_kind(house, "main", kind), cfg))
    pattern = next(p for i, p in _patterns(root).items() if i.startswith(f"hatch-{kind}-"))
    cell = (float(pattern.get("width")), float(pattern.get("height")))
    coords = re.findall(r"M([\d.]+),([\d.]+)L([\d.]+),([\d.]+)", pattern.find("{*}path").get("d"))
    assert coords and all(0 <= float(v) <= limit for c in coords
                          for v, limit in zip(c, cell * 2, strict=True))
