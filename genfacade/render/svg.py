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

from genfacade import roof
from genfacade.config import Axes, Config, DoorLook, Hatch, Levels, Sheet, SheetLayout, TrimLook
from genfacade.render import hatch, sheet_format
from genfacade.render.sheet_format import num
from genfacade.schema import (
    EPS,
    CanopyKind,
    Element,
    ElementClass,
    FacadeSheet,
    HouseSpec,
    HouseTrim,
    MaterialZone,
    PaletteRole,
    Point,
    Polygon,
    ShutterKind,
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

    above: Polygon | None = None
    roof: list[Polygon] = []

    def height(self, facade: SideFacade) -> float:
        """Верх рисунка стороны: силуэт стены, стена над карнизом и кровля."""
        shapes = [facade.silhouette or [], self.above or [], *self.roof]
        return max(y for shape in shapes for _, y in shape)


NOTHING_ABOVE = Top()  # плоская крыша: над карнизом ничего


def tops(sheet: FacadeSheet, cfg: Config) -> list[Top]:
    """Что над карнизом у каждой стороны листа; скаты не строятся — пусто."""
    line = roof.roofline(sheet)
    if line is None:
        return [NOTHING_ABOVE for _ in sheet.facades]
    return [Top(roof.above_eaves(line, k), roof.roof_view(line, k, cfg.sheet.roof.thickness_m))
            for k in range(len(sheet.facades))]


class Marks(NamedTuple):
    """Подписи одного фасада."""

    levels: list[float]
    axes: tuple[str, str]  # левая и правая ось, если смотреть снаружи
    sheet: Sheet


def points(poly: Polygon) -> str:
    return " ".join(f"{num(x)},{num(y)}" for x, y in poly)


def add_line(g: ElementTree.Element, css_class: str, start: Point, end: Point) -> None:
    (x1, y1), (x2, y2) = start, end
    ElementTree.SubElement(g, "line", {"class": css_class, "x1": num(x1), "y1": num(y1),
                                       "x2": num(x2), "y2": num(y2)})


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
    _facade_geometry(root, facade, (0.0, top), pen)
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
    if top.above:  # стена над карнизом — основной отделкой, как стена под ним
        ElementTree.SubElement(g, "polygon", {"class": "above-eaves", "points": points(top.above),
                                              "fill": _main(pen)})
    for e in facade.elements:
        _element(g, e, pen, facade.zones)
    for shape in top.roof:  # кровля — поверх: свес закрывает верх стены
        ElementTree.SubElement(g, "polygon", {"class": "roof", "points": points(shape),
                                              "fill": _roof_fill(pen)})
    return g


def _main(pen: Pen) -> str:
    main = PaletteRole.MAIN
    return paint(main, pen) if main in pen.colors else pen.cfg.library.fill.wall


def _roof_fill(pen: Pen) -> str:
    """Кровля — материалом крыши дома, если он в палитре; иначе заливкой «прочее»."""
    material = pen.roof
    return paint(material, pen) if material in pen.colors else pen.cfg.library.fill.other


def _overlay(g: ElementTree.Element, facade: SideFacade, violations: list[Violation]) -> None:
    """Запретные зоны — полосой во всю высоту стены; нарушение — рамкой вокруг элемента,
    а без элемента (углы, проём плана) — рамкой по стене."""
    top = _top(facade)
    for z in facade.side.forbidden:
        _box(g, "forbidden-zone", (z.x0_m, 0.0, z.x1_m - z.x0_m, top))
    boxes = {e.id: (e.x_m, e.y_m, e.w_m, e.h_m) for e in facade.elements}
    for v in violations:
        box = boxes.get(v.element or "", (0.0, 0.0, facade.side.length_m, top))
        node = _box(g, f"violation {v.severity}", box)
        ElementTree.SubElement(node, "title").text = f"{v.rule}: {v.message}"


def _box(g: ElementTree.Element, css_class: str, box: tuple[float, ...]) -> ElementTree.Element:
    x, y, w, h = box
    return ElementTree.SubElement(g, "rect", {"class": css_class, "x": num(x), "y": num(y),
                                              "width": num(w), "height": num(h)})


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
    if _by_material(e, pen):
        return paint(e.material, pen)
    return element_fill(e, pen)


def _element(g: ElementTree.Element, e: Element, pen: Pen, zones: list[MaterialZone]) -> None:
    lib = pen.cfg.library
    attrs = {
        sheet_format.CLS: e.cls, sheet_format.ID: e.id,
        "x": num(e.x_m), "y": num(e.y_m), "width": num(e.w_m), "height": num(e.h_m),
        "fill": element_paint(e, pen),
    }
    optional = {sheet_format.FLOOR: e.floor, sheet_format.PARENT: e.parent}
    attrs |= {k: str(v) for k, v in optional.items() if v is not None} | _material(e, zones)
    if e.variant is not None:
        attrs[sheet_format.VARIANT] = sheet_format.encode_variant(e.variant)
    if e.fixed:
        attrs[sheet_format.FIXED] = ",".join(e.fixed)
    if e.cls is ElementClass.WINDOW:
        attrs["fill"] = lib.fill.glass  # материал окна красит раму
        if e.material:
            attrs["stroke"] = pen.colors[e.material]
    framed = e.cls is ElementClass.CANOPY and pen.trim.canopy in (CanopyKind.GABLE,
                                                                   CanopyKind.BRACKET)
    if framed:  # рисунок вида — не прямоугольник: прямоугольник остаётся только для разбора
        attrs["class"] = "trim-frame"
    ElementTree.SubElement(g, "rect", attrs)
    if e.cls is ElementClass.WINDOW and e.variant is not None:
        _mullions(g, e, (e.x_m, e.y_m, e.w_m, e.h_m))
    elif e.cls is ElementClass.DOOR and e.variant is not None:
        glass = _door_glass(e, pen.cfg.sheet.door)
        _box(g, "door-glass", glass).set("fill", lib.fill.glass)
        _mullions(g, e, glass)
    elif e.cls is ElementClass.BLIND:
        _shutter(g, e, pen.trim.shutters, pen.cfg.sheet.trim)
    elif framed:
        _canopy(g, e, pen.trim.canopy, pen.cfg.sheet.trim).set("fill", attrs["fill"])


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


def _shutter(g: ElementTree.Element, e: Element, kind: ShutterKind, look: TrimLook) -> None:
    """Рисунок створки ставни по виду дома: планки жалюзи, доски или две филёнки."""
    x0, y0, w, h = e.x_m, e.y_m, e.w_m, e.h_m
    if kind is ShutterKind.LOUVERED:
        for k in range(1, int(h / look.louver_step_m)):
            add_line(g, "trim-line", (x0, y0 + k * look.louver_step_m),
                     (x0 + w, y0 + k * look.louver_step_m))
    elif kind is ShutterKind.BOARD:
        for k in range(1, int(w / look.board_step_m)):
            add_line(g, "trim-line", (x0 + k * look.board_step_m, y0),
                     (x0 + k * look.board_step_m, y0 + h))
    elif kind is ShutterKind.PANEL:
        inset = w * look.panel_inset
        half = (h - 3 * inset) / 2
        for y in (y0 + inset, y0 + 2 * inset + half):
            _box(g, "trim-line", (x0 + inset, y, w - 2 * inset, half)).set("fill", "none")


def _canopy(g: ElementTree.Element, e: Element, kind: CanopyKind,
            look: TrimLook) -> ElementTree.Element:
    """Двускатный козырёк — треугольник; на кронштейнах — плита сверху и два кронштейна."""
    x0, y0, w, h = e.x_m, e.y_m, e.w_m, e.h_m
    if kind is CanopyKind.GABLE:
        shape = [(x0, y0), (x0 + w, y0), (x0 + w / 2, y0 + h)]
        return ElementTree.SubElement(g, "polygon", {"points": points(shape)})
    slab = min(look.slab_m, h)
    top = ElementTree.SubElement(g, "g")
    _box(top, "", (x0, y0 + h - slab, w, slab))
    for at, side in ((x0 + w * look.bracket_at, 1), (x0 + w * (1 - look.bracket_at), -1)):
        shape = [(at, y0 + h - slab), (at, y0), (at + side * look.bracket_w_m, y0 + h - slab)]
        ElementTree.SubElement(top, "polygon", {"points": points(shape)})
    return top


def _mullions(g: ElementTree.Element, e: Element, glass: tuple[float, ...]) -> None:
    """Деление стекла на створки — линии поверх него, в разбор не входят."""
    v, (x0, y0, w, h) = e.variant, glass
    for x in (x0 + w * i / v.cols for i in range(1, v.cols)):
        add_line(g, "mullion", (x, y0), (x, y0 + h))
    for y in (y0 + h * j / v.rows for j in range(1, v.rows)):
        add_line(g, "mullion", (x0, y), (x0 + w, y))


def _door_glass(e: Element, look: DoorLook) -> tuple[float, float, float, float]:
    """Где у двери стекло: в полотне или фрамугой сверху (спека facade, «Элемент», вариант)."""
    if e.variant.kind is VariantKind.TRANSOM:
        h = e.h_m * look.transom_share
        return (e.x_m, e.y_m + e.h_m - h, e.w_m, h)
    low, high = look.glazed_span
    inset = e.w_m * look.glass_inset
    return (e.x_m + inset, e.y_m + e.h_m * low, e.w_m - 2 * inset, e.h_m * (high - low))


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
