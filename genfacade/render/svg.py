"""Шаг 6: лист фасадов в SVG (`facade: Элементы в SVG`, `facade: JSON и SVG — одно содержимое`).

Координаты — метры натуры; оформление — config/sheet.toml (размеры) и
config/sheet.css (линии, шрифты), заливки по умолчанию — config/library.toml.
Каждый элемент и зона несут в `data-*` всё, что есть в JSON (sheet_format.py), поэтому
SVG разбирается обратно без потерь. Геометрия фасада — в группе с осью y вверх,
подписи — в обычной.
"""

import math
from typing import NamedTuple
from xml.etree import ElementTree

import shapely

from genfacade import roof, roof_items, skylights, window_shape
from genfacade.config import Axes, Config, DoorLook, Hatch, Levels, Sheet, SheetLayout
from genfacade.render import hatch, sheet_format, trim
from genfacade.render.shapes import add_line, box, points
from genfacade.render.sheet_format import num
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    HouseSpec,
    HouseTrim,
    MaterialZone,
    PaletteRole,
    Point,
    Polygon,
    SideFacade,
    VariantKind,
    Violation,
)
from genfacade.unfold import plan_corners


class Pen(NamedTuple):
    """Чем красить: настройки, цвета материалов и виды выводимых элементов этого дома."""

    cfg: Config
    colors: dict[str, str]  # id материала палитры → цвет
    kinds: dict[str, str]  # id материала палитры → вид из библиотеки
    trim: HouseTrim = HouseTrim()
    roof: str | None = None  # id материала кровли в палитре


def pen_for(sheet: FacadeSheet, cfg: Config) -> Pen:
    kinds = {m.id: m.kind for m in sheet.spec.materials}
    return Pen(cfg, palette_colors(sheet.spec, cfg), kinds, sheet.spec.trim,
               sheet.spec.roof.material)


class Top(NamedTuple):
    """Что над карнизом стены (roof.py, gf#320): стена выше карниза и кровля на виде."""

    above: list[Polygon] = []
    roof: list[Polygon] = []
    seams: list[list[Point]] = []  # линии примыкания кровли нижней части к стене верхней (gf#322)
    gable: Polygon | None = None  # фронтон — место окон над карнизом (`roof.gables`, gf#321)
    items: list[tuple[roof_items.ItemKind, Polygon]] = []  # труба, желоб, трубы (gf#454)
    skylights: list[tuple[Polygon, Polygon]] = []  # мансардные окна на кровле: рамка и стекло

    def height(self, facade: SideFacade) -> float:
        """Верх рисунка стороны: силуэт стены, стена над карнизом, кровля и труба."""
        shapes = [facade.silhouette or [], *self.above, *self.roof, *(p for _, p in self.items)]
        return max(y for shape in shapes for _, y in shape)


RECT_POINTS = 4  # у прямоугольного силуэта четыре вершины
NOTHING_ABOVE = Top()  # плоская крыша: над карнизом ничего


def tops(sheet: FacadeSheet, cfg: Config) -> list[Top]:
    """Что над карнизом у каждой стороны листа; скаты не строятся — пусто."""
    house = roof.roofs(sheet)
    if house is None:
        return [NOTHING_ABOVE for _ in sheet.facades]
    gables = roof.sheet_gables(sheet)
    found = roof_items.roof_items(sheet, cfg.sheet.roof_items)
    out = []
    for k in range(len(sheet.facades)):
        walls, seams = roof.joint_view(house, k)
        out.append(Top(roof.house_above(house, k) + walls,
                       roof.house_view(house, k, cfg.sheet.roof.thickness_m), seams, gables[k],
                       roof_items.view(found, house.corners, k)))
    return _with_skylights(out, sheet, cfg, house)


def _with_skylights(out: list[Top], sheet: FacadeSheet, cfg: Config, house: roof.HouseRoof
                    ) -> list[Top]:
    """Мансардные окна (gf#456) на видах: поднятые с грани ската на верх кровли, как на ней."""
    lights = skylights.find(sheet, cfg.sheet.skylight)
    dz = cfg.sheet.roof.thickness_m + cfg.sheet.skylight.lift_m
    lights = [skylights.raised(s, dz) for s in lights]
    return [top._replace(skylights=skylights.on_view(lights, *roof.axis(house.corners, k)[:2],
                                                     top.roof))
            for k, top in enumerate(out)]


class Marks(NamedTuple):
    """Подписи одного фасада."""

    levels: list[float]
    axes: tuple[str, str]  # левая и правая ось, если смотреть снаружи
    sheet: Sheet


def add_text(g: ElementTree.Element, css_class: str, at: Point, text: str) -> None:
    x, y = at
    node = ElementTree.SubElement(g, "text", {"class": css_class, "x": num(x), "y": num(y)})
    node.text = text


def canvas(width: float, height: float, css: str,
           patterns: list[ElementTree.Element] = ()) -> ElementTree.Element:
    """Корень SVG в метрах: стиль, рисунки материалов (`<defs>`) и белый фон."""
    root = ElementTree.Element("svg", {"xmlns": sheet_format.SVG_NS,
                                       "viewBox": f"0 0 {num(width)} {num(height)}"})
    ElementTree.SubElement(root, "style").text = css
    if patterns:
        ElementTree.SubElement(root, "defs").extend(patterns)
    # Размер фона числом, не 100%: проценты считаются от viewBox, и при масштабе
    # в смотрелке фон обрезался бы.
    ElementTree.SubElement(root, "rect", {"class": "background",
                                          "width": num(width), "height": num(height)})
    return root


def sheet_svg(sheet: FacadeSheet, cfg: Config, violations: list[Violation] | None = None,
              annotations: bool = True) -> str:
    """Лист всех фасадов; силуэты стен должны быть посчитаны (unfold).

    violations — для трассы шагов 4–5: поверх листа запретные зоны и нарушения валидатора.
    Слой без data-cls, поэтому разбор листа его не видит. annotations — отметки, оси, земля
    и подписи: оформление листа (шаг 6), на промежуточных шагах их нет.
    """
    over = tops(sheet, cfg)
    cells, width, height = _layout(sheet, over, cfg.sheet.sheet)
    mm_per_m = 1000 / cfg.sheet.sheet.scale
    pen = pen_for(sheet, cfg)
    above = [PaletteRole.MAIN, pen.roof] if any(t.roof for t in over) else []
    root = canvas(width, height, cfg.css, _patterns(sheet.facades, pen, above))
    root.set("width", f"{width * mm_per_m:.0f}mm")
    root.set("height", f"{height * mm_per_m:.0f}mm")
    axes = _axis_labels(sheet, cfg.sheet.axes.letters)
    marks_at = levels(sheet.spec, cfg.sheet.levels)
    for facade, origin, top in zip(sheet.facades, cells, over, strict=True):
        g = _facade_geometry(root, facade, origin, pen, top)
        if violations is not None:
            _overlay(g, facade, [v for v in violations if v.side == facade.side.index])
        if annotations:
            marks = Marks(marks_at, axes[facade.side.index], cfg.sheet)
            _annotations(root, origin, facade.side.length_m, marks)
    ElementTree.indent(root)
    return ElementTree.tostring(root, encoding="unicode")


def facade_svg(facade: SideFacade, pen: Pen) -> str:
    """Одна стена без подписей: SVG ровно по стене (длина × верх силуэта), левый край — x = 0.
    Для текстуры дома объёмом (render/house3d.py)."""
    top = _top(facade)
    root = canvas(facade.side.length_m, top, pen.cfg.css, _patterns([facade], pen))
    if len(facade.silhouette or []) > RECT_POINTS:  # ступень (gf#322): над ней — не белый фон
        root.remove(next(e for e in root if e.get("class") == "background"))
    _facade_geometry(root, facade, (0.0, top), pen)
    return ElementTree.tostring(root, encoding="unicode")


def facade_roof_svg(sheet: FacadeSheet, cfg: Config, k: int) -> str:
    """Один фасад листа вместе с кровлей над ним, без подписей: то, как его рисует лист, но
    кадр — по стене и свесу, а не по всему листу. Для образцов каталога смотрелки (gf#354)."""
    facade, top = sheet.facades[k], tops(sheet, cfg)[k]
    pen, pad = pen_for(sheet, cfg), sheet.spec.roof.reach
    above = [PaletteRole.MAIN, pen.roof] if top.roof else []
    root = canvas(facade.side.length_m + 2 * pad, top.height(facade), cfg.css,
                  _patterns([facade], pen, above))
    _facade_geometry(root, facade, (pad, top.height(facade)), pen, top)
    return ElementTree.tostring(root, encoding="unicode")


def palette_colors(spec: HouseSpec, cfg: Config) -> dict[str, str]:
    """id материала палитры → цвет: свой или цвет вида из библиотеки."""
    kinds = cfg.library.kinds
    colors = {}
    for m in spec.materials:
        if m.color is None and m.kind not in kinds:
            raise ValueError(f"материал {m.id}: нет цвета, и вида {m.kind} нет в библиотеке")
        colors[m.id] = m.color or kinds[m.kind]
    return colors


def _hatch_of(material: str, pen: Pen) -> Hatch | None:
    """Рисунок вида материала палитры; вида нет в [patterns] библиотеки — None, заливка цветом.
    Единственное место, где решается, рисунком ли залит материал: `paint` и `_patterns`."""
    return pen.cfg.library.patterns.get(pen.kinds[material])


def paint(material: str, pen: Pen) -> str:
    """Чем залить зону или элемент из материала палитры: рисунком вида (`url(#…)` на паттерн
    листа), если у вида он есть в библиотеке, иначе цветом."""
    color = pen.colors[material]
    if _hatch_of(material, pen) is None:
        return color
    return f"url(#{hatch.pattern_id(pen.kinds[material], color)})"


def swatch(material: str, pen: Pen) -> dict | None:
    """Ячейка рисунка материала для 3D (gf#353): SVG и её размер в метрах; рисунка у вида нет —
    None, 3D красит цветом. Тот же рисунок и цвет, что у `paint` на листе."""
    look = _hatch_of(material, pen)
    if look is None:
        return None
    width, height = hatch.tile_m(look)
    return {"svg": hatch.swatch(pen.kinds[material], look, pen.colors[material],
                                pen.cfg.library.pattern_darken),
            "width_m": width, "height_m": height}


def element_material(e: Element, pen: Pen) -> str | None:
    """Материал палитры, которым элемент залит на листе, — или None, если он залит цветом класса."""
    return e.material if _by_material(e, pen) else None


def _by_material(e: Element, pen: Pen) -> bool:
    """Элемент залит материалом палитры: материал есть, а класс не из unhatched_cls (те рисуют
    себя сами). Одно правило на заливку элемента (`element_paint`) и на набор паттернов листа."""
    return e.material is not None and e.cls not in pen.cfg.library.unhatched_cls


def _painted(facade: SideFacade, pen: Pen) -> list[str]:
    """Материалы, которыми на этой стене красят зоны и элементы."""
    by_material = [e.material for e in facade.elements if _by_material(e, pen)]
    return [z.material for z in facade.zones] + by_material


def _patterns(facades: list[SideFacade], pen: Pen,
              above: list[str | None] = ()) -> list[ElementTree.Element]:
    """Рисунки материалов, которые нужны листу, — по одному на пару вид × цвет, а не на зону;
    `above` — материалы над карнизом (стена выше карниза и кровля, gf#320)."""
    found = {}
    painted = [m for f in facades for m in _painted(f, pen)] + [m for m in above if m in pen.colors]
    for material in painted:
        kind, color = pen.kinds[material], pen.colors[material]
        if (look := _hatch_of(material, pen)) is not None:
            found.setdefault(hatch.pattern_id(kind, color),
                             hatch.pattern(kind, look, color, pen.cfg.library.pattern_darken))
    return list(found.values())


def _top(facade: SideFacade) -> float:
    return max(y for _, y in facade.silhouette or [])


def _layout(sheet: FacadeSheet, over: list[Top],
            lay: SheetLayout) -> tuple[list[tuple[float, float]], float, float]:
    """Фасады рядами по lay.columns; (ox, oy) — левый край стены и уровень земли. Свес кровли
    выходит за стену по краям — он в зазоре между фасадами."""
    col_w = max(f.side.length_m for f in sheet.facades) + lay.gap_x_m
    row_h = max(t.height(f) for f, t in zip(sheet.facades, over, strict=True)) + lay.gap_y_m
    cells = []
    for i, _ in enumerate(sheet.facades):
        row, col = divmod(i, lay.columns)
        ground = lay.margin_top_m + (row + 1) * row_h - lay.gap_y_m
        cells.append((lay.margin_left_m + col * col_w, ground))
    rows = math.ceil(len(sheet.facades) / lay.columns)
    return cells, lay.margin_left_m + lay.columns * col_w, lay.margin_top_m + rows * row_h


def _facade_geometry(root: ElementTree.Element, facade: SideFacade, origin,
                     pen: Pen, top: Top = NOTHING_ABOVE) -> ElementTree.Element:
    ox, oy = origin
    g = ElementTree.SubElement(root, "g", {
        "class": sheet_format.FACADE_CLASS, sheet_format.SIDE: str(facade.side.index),
        "transform": f"translate({num(ox)},{num(oy)}) scale(1,-1)",
    })
    silhouette = points(facade.silhouette or [])
    ElementTree.SubElement(g, "polygon", {"class": "wall", "points": silhouette,
                                 "fill": pen.cfg.library.fill.wall})
    for z in facade.zones:
        _zone(g, z, pen)
    # Контур — до элементов: карниз у края стены ложится поверх линии, а не под неё.
    ElementTree.SubElement(g, "polygon", {"class": "outline", "points": silhouette})
    _items(g, top, pen, roof_items.ItemKind.CHIMNEY)  # труба — за стеной над карнизом и кровлей
    for shape in top.above:  # стена над карнизом — основной отделкой, как стена под ним
        ElementTree.SubElement(g, "polygon", {"class": "above-eaves", "points": points(shape),
                                              "fill": _main(pen)})
    room = None if top.gable is None else window_shape.gable_room(
        facade.side.length_m, min(y for _, y in top.gable), top.gable,
        pen.cfg.checks.slope_offset_m)
    by = {e.id: e for e in facade.elements}
    for e in facade.elements:
        _element(g, e, pen, facade, _shape(e, room), _casing_shape(e, by, room))
    for shape in top.roof:  # кровля — поверх: свес закрывает верх стены
        ElementTree.SubElement(g, "polygon", {"class": "roof", "points": points(shape),
                                              "fill": _roof_fill(pen)})
    for frame, glass in top.skylights:  # мансардные окна — на кровле поверх неё
        for shape, name in ((frame, "skylight"), (glass, "skylight-glass")):
            ElementTree.SubElement(g, "polygon", {"class": name, "points": points(shape),
                                                  "fill": pen.cfg.library.fill.glass})
    for seam in top.seams:  # примыкание кровли нижней части к стене верхней
        ElementTree.SubElement(g, "polyline", {"class": "outline joint", "points": points(seam)})
    _items(g, top, pen, roof_items.ItemKind.GUTTER)  # желоб и трубы — на кромке кровли и стене
    _items(g, top, pen, roof_items.ItemKind.PIPE)
    return g


def _items(g: ElementTree.Element, top: Top, pen: Pen, kind: roof_items.ItemKind) -> None:
    """Труба, желоба или водосточные трубы вида (gf#454): цвет — из `[roof_items]` листа."""
    look = pen.cfg.sheet.roof_items
    fill = look.chimney_fill if kind is roof_items.ItemKind.CHIMNEY else look.gutter_fill
    for found, shape in top.items:
        if found is kind:
            ElementTree.SubElement(g, "polygon", {"class": f"roof-item {kind}",
                                                  "points": points(shape), "fill": fill})


def _main(pen: Pen) -> str:
    main = PaletteRole.MAIN
    return paint(main, pen) if main in pen.colors else pen.cfg.library.fill.wall


def _roof_fill(pen: Pen) -> str:
    """Кровля — материалом крыши дома, если он в палитре; иначе заливкой «прочее»."""
    material = pen.roof
    return paint(material, pen) if material in pen.colors else pen.cfg.library.fill.other


def _overlay(g: ElementTree.Element, facade: SideFacade, violations: list[Violation]) -> None:
    """Запретные зоны — полосой во всю высоту стены, зона под кровлей соседней части — по своей
    высоте; нарушение — рамкой вокруг элемента, а без элемента (углы, проём плана) — рамкой по
    стене."""
    top = _top(facade)
    for z in facade.side.forbidden:
        y0, y1 = (0.0, top) if z.y0_m is None or z.y1_m is None else (z.y0_m, z.y1_m)
        box(g, "forbidden-zone", (z.x0_m, y0, z.x1_m - z.x0_m, y1 - y0))
    boxes = {e.id: (e.x_m, e.y_m, e.w_m, e.h_m) for e in facade.elements}
    for v in violations:
        frame = boxes.get(v.element or "", (0.0, 0.0, facade.side.length_m, top))
        node = box(g, f"violation {v.severity}", frame)
        ElementTree.SubElement(node, "title").text = f"{v.rule}: {v.message}"


def _zone(g: ElementTree.Element, z: MaterialZone, pen: Pen) -> None:
    ElementTree.SubElement(g, "polygon", {
        sheet_format.ROLE: z.role, sheet_format.MATERIAL: z.material, "points": points(z.shape),
        "fill": paint(z.material, pen),
    })


def element_fill(e: Element, pen: Pen) -> str:
    """Цвет элемента: материал палитры дома, иначе цвет класса из библиотеки. Им же красит
    выступы дом объёмом (render/house3d.py)."""
    lib = pen.cfg.library
    return pen.colors.get(e.material or "", lib.class_fill.get(e.cls, lib.fill.other))


def element_paint(e: Element, pen: Pen) -> str:
    """Заливка прямоугольника элемента: рисунок вида его материала, а без рисунка или у класса
    из unhatched_cls — цвет (element_fill)."""
    if (material := element_material(e, pen)) is not None:
        return paint(material, pen)
    return element_fill(e, pen)


def _glass(g: ElementTree.Element, e: Element, attrs: dict[str, str],
           shape: Polygon | None) -> None:
    """Стекло окна поверх рамки: у окна не прямоугольником (gf#319) — контур, деление рамы внутри
    него; у прямоугольного — деление рамы по рамке."""
    box = (e.x_m, e.y_m, e.w_m, e.h_m)
    if shape:
        drawn = {"class": "window-shape", "points": points(shape), "fill": attrs["fill"]}
        if "stroke" in attrs:
            drawn["stroke"] = attrs["stroke"]
        ElementTree.SubElement(g, "polygon", drawn)
        if e.variant is not None:
            _mullions(g, e, box, shapely.Polygon(shape))
    elif e.variant is not None:
        _mullions(g, e, box)


def _shape(e: Element, room: shapely.Geometry | None) -> Polygon | None:
    """Контур окна не прямоугольником — по его виду (gf#319); прямоугольное окно — None."""
    if e.cls is not ElementClass.WINDOW:
        return None
    return _not_box(e, window_shape.outline(e, room))


def _not_box(e: Element, shape: Polygon) -> Polygon | None:
    """Контур, если он не прямоугольник рамки элемента, иначе None."""
    box = shapely.box(e.x_m, e.y_m, e.x_m + e.w_m, e.y_m + e.h_m)
    return None if shapely.Polygon(shape).equals(box) else shape


def _casing_shape(e: Element, by: dict[str, Element],
                  room: shapely.Geometry | None) -> Polygon | None:
    """Контур наличника окна не прямоугольником (gf#319); наличник прямоугольного окна — None."""
    w = by.get(e.parent or "")
    if e.cls is not ElementClass.MOLDING or w is None or w.cls is not ElementClass.WINDOW:
        return None
    return _not_box(e, window_shape.casing(w, e, room))


def _element(g: ElementTree.Element, e: Element, pen: Pen, facade: SideFacade,
             shape: Polygon | None = None, round_casing: Polygon | None = None) -> None:
    lib = pen.cfg.library
    attrs = {
        sheet_format.CLS: e.cls, sheet_format.ID: e.id,
        "x": num(e.x_m), "y": num(e.y_m), "width": num(e.w_m), "height": num(e.h_m),
        "fill": element_paint(e, pen),
    }
    optional = {sheet_format.FLOOR: e.floor, sheet_format.PARENT: e.parent}
    attrs |= {k: str(v) for k, v in optional.items() if v is not None} | _material(e, facade.zones)
    if e.variant is not None:
        attrs[sheet_format.VARIANT] = sheet_format.encode_variant(e.variant)
    if e.fixed:
        attrs[sheet_format.FIXED] = ",".join(e.fixed)
    if e.cls is ElementClass.WINDOW:
        attrs["fill"] = lib.fill.glass  # материал окна красит раму
        if e.material:
            attrs["stroke"] = pen.colors[e.material]
    framed = _framed(e, pen) or round_casing is not None
    if framed or shape:  # рисунок вида — не прямоугольник: прямоугольник остаётся для разбора
        attrs["class"] = "trim-frame"
    ElementTree.SubElement(g, "rect", attrs)
    if e.cls is ElementClass.WINDOW:
        _glass(g, e, attrs, shape)
    elif e.cls is ElementClass.DOOR:
        _door(g, e, pen)
    elif e.cls is ElementClass.BLIND:
        trim.shutter(g, e, pen.cfg.derive.find("shutters", pen.trim.shutters), pen.cfg.sheet.trim)
    elif framed:
        drawn = (trim.casing_round(g, round_casing) if round_casing is not None
                 else _outline(g, e, pen, facade))
        drawn.set("fill", attrs["fill"])


def foot_of(e: Element, elements: list[Element]) -> float:
    """Низ проёма, к которому прикреплён выводимый элемент (родитель); родителя нет — свой низ.
    Столбы навеса опускаются до него (рисунок и 3D)."""
    return next((p.y_m for p in elements if p.id == e.parent), e.y_m)


def _door(g: ElementTree.Element, e: Element, pen: Pen) -> None:
    """Дверь: рисунок полотна — по виду дома, стекло поверх него — по варианту элемента."""
    leaf = pen.cfg.derive.look("door", pen.trim.door)
    trim.door(g, e, leaf, pen.cfg.library.fill.glass)
    if e.variant is not None:
        glass = _door_glass(e, pen.cfg.sheet.door, trim.leaf_box(e, leaf))
        box(g, "door-glass", glass).set("fill", pen.cfg.library.fill.glass)
        _mullions(g, e, glass)


def _framed(e: Element, pen: Pen) -> bool:
    """Элемент со своим контуром (сандрик, двускатный и прочие козырьки): прямоугольник остаётся
    только для разбора, красится контур."""
    if e.cls is ElementClass.CANOPY:
        look = pen.cfg.derive.find("canopy", pen.trim.canopy)
        return look is not None and trim.canopy_framed(look.shape)
    if e.cls is ElementClass.MOLDING:
        look = pen.cfg.derive.find("casing", pen.trim.casing)
        return look is not None and trim.casing_framed(look.shape)
    return False


def _outline(g: ElementTree.Element, e: Element, pen: Pen,
             facade: SideFacade) -> ElementTree.Element:
    if e.cls is ElementClass.CANOPY:
        look = pen.cfg.derive.find("canopy", pen.trim.canopy)
        return trim.canopy(g, e, look, pen.cfg.sheet.trim, foot_of(e, facade.elements))
    return trim.casing(g, e, pen.cfg.derive.find("casing", pen.trim.casing))


def _material(e: Element, zones: list[MaterialZone]) -> dict[str, str]:
    """Материал элемента в SVG (`facade: Элементы в SVG`): свой, а без своего — зоны под его
    центром (верхней на листе, то есть последней) с пометкой, что он не свой. Цвет от этого
    не меняется: окно и дверь без своего материала красятся по классу."""
    if e.material is not None:
        return {sheet_format.MATERIAL: e.material}
    center = shapely.Point(e.x_m + e.w_m / 2, e.y_m + e.h_m / 2)
    under = [z for z in zones if shapely.Polygon(z.shape).covers(center)]
    if not under:
        return {}
    return {sheet_format.MATERIAL: under[-1].material, sheet_format.ZONE_MATERIAL: "true"}


def _mullions(g: ElementTree.Element, e: Element, glass: tuple[float, ...],
              inside: shapely.Polygon | None = None) -> None:
    """Деление стекла на створки — линии поверх него, в разбор не входят; у окна не
    прямоугольником — в пределах контура (inside)."""
    v, (x0, y0, w, h) = e.variant, glass
    lines = [((x, y0), (x, y0 + h)) for x in (x0 + w * i / v.cols for i in range(1, v.cols))]
    lines += [((x0, y), (x0 + w, y)) for y in (y0 + h * j / v.rows for j in range(1, v.rows))]
    for a, b in lines:
        if inside is not None:
            cut = inside.intersection(shapely.LineString([a, b]))
            if cut.is_empty or cut.geom_type != "LineString":
                continue
            a, b = cut.coords[0], cut.coords[-1]
        add_line(g, "mullion", a, b)


def _door_glass(e: Element, look: DoorLook,
                leaf: tuple[float, ...]) -> tuple[float, float, float, float]:
    """Где у двери стекло: в полотне или фрамугой сверху (спека facade, «Элемент», вариант); leaf —
    полотно: проём, а при боковых стёклах без них."""
    x, y, w, h = leaf
    if e.variant.kind is VariantKind.TRANSOM:
        return (x, y + h - h * look.transom_share, w, h * look.transom_share)
    low, high = look.glazed_span
    return (x + w * look.glass_inset, y + h * low, w * (1 - 2 * look.glass_inset), h * (high - low))


def _axis_labels(sheet: FacadeSheet, letters: str) -> dict[int, tuple[str, str]]:
    """Оси на краях каждого фасада, как в эскизном проекте: 1, 2… по x, буквы по y.

    Сторона i идёт от угла i к углу i+1 по часовой; снаружи её левый край — угол i+1.
    """
    sides = [f.side for f in sheet.facades]
    corners = plan_corners(sides)

    def key(v: float) -> int:  # координаты в пределах EPS — одна ось
        return round(v / EPS)

    xs = sorted({key(x) for x, _ in corners})
    ys = sorted({key(y) for _, y in corners})

    def label(corner, side) -> str:
        if side.runs_along_x:
            return str(xs.index(key(corner[0])) + 1)
        return letters[ys.index(key(corner[1]))]

    return {
        s.index: (label(corners[(k + 1) % len(corners)], s), label(corners[k], s))
        for k, s in enumerate(sides)
    }


def levels(spec: HouseSpec, cfg: Levels) -> list[float]:
    """Земля, цоколь, этажи, карниз — одни на все фасады дома."""
    uniq: list[float] = []
    for v in sorted([0.0, *spec.floor_levels(), spec.eaves_m]):
        if not uniq or v - uniq[-1] > cfg.merge_below_m:
            uniq.append(v)
    return uniq


def _annotations(root: ElementTree.Element, origin, length: float, marks: Marks) -> None:
    """Линия земли, отметки уровней справа, оси по краям, подпись снизу."""
    ox, oy = origin
    cfg = marks.sheet
    g = ElementTree.SubElement(root, "g", {"class": "annotations",
                                  "transform": f"translate({num(ox)},{num(oy)})"})
    ext = cfg.ground.extend_m
    add_line(g, "ground", (-ext, 0.0), (length + ext, 0.0))
    for v in marks.levels:
        level_mark(g, length + cfg.levels.offset_m, v, cfg.levels)
    for x, name in ((0.0, marks.axes[0]), (length, marks.axes[1])):
        _axis_bubble(g, x, name, cfg.axes)
    title = f"Фасад в осях {marks.axes[0]}–{marks.axes[1]}"
    add_text(g, "title", (length / 2, cfg.title.y_m), title)


def level_mark(g: ElementTree.Element, x: float, level: float, cfg: Levels) -> None:
    """Отметка уровня: треугольник на полке и значение над ней, «+3,300»."""
    y = -level
    add_line(g, "level-shelf", (x - cfg.shelf_left_m, y), (x + cfg.shelf_right_m, y))
    half, height = cfg.marker_half_width_m, cfg.marker_height_m
    marker = [(x, y), (x - half, y - height), (x + half, y - height)]
    ElementTree.SubElement(g, "polygon", {"class": "level-marker", "points": points(marker)})
    ground = level == 0.0
    # Земля подписана под полкой: цоколь бывает ниже высоты шрифта, подписи слиплись бы.
    ty = y + cfg.text_below_m if ground else y - cfg.text_above_m
    label = f"{'±' if ground else '+'}{level:.3f}".replace(".", ",")
    add_text(g, "level-text", (x + cfg.text_dx_m, ty), label)


def _axis_bubble(g: ElementTree.Element, x: float, name: str, cfg: Axes) -> None:
    add_line(g, "axis-line", (x, cfg.line_from_m), (x, cfg.line_to_m))
    ElementTree.SubElement(g, "circle", {"class": "axis-bubble", "cx": num(x),
                                "cy": num(cfg.bubble_y_m), "r": num(cfg.bubble_radius_m)})
    add_text(g, "axis-text", (x, cfg.bubble_y_m + cfg.text_dy_m), name)
