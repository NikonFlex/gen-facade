"""Шаг 6: лист фасадов в SVG (facade.md, правила 5–7).

Координаты — метры натуры; оформление — config/sheet.toml (размеры) и
config/sheet.css (линии, шрифты), заливки по умолчанию — config/library.toml.
Каждый элемент и зона несут в `data-*` всё, что есть в JSON (sheet_format.py), поэтому
SVG разбирается обратно без потерь. Геометрия фасада — в группе с осью y вверх,
подписи — в обычной.
"""

import math
from typing import NamedTuple
from xml.etree import ElementTree

from genfacade.config import Axes, Config, Levels, Sheet, SheetLayout
from genfacade.render import sheet_format
from genfacade.render.sheet_format import num
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    MaterialZone,
    Point,
    Polygon,
    SideFacade,
    Violation,
)
from genfacade.unfold import plan_corners


class Pen(NamedTuple):
    """Чем красить: настройки и цвета материалов этого дома."""

    cfg: Config
    colors: dict[str, str]  # id материала палитры → цвет


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


def canvas(width: float, height: float, css: str) -> ElementTree.Element:
    """Корень SVG в метрах: стиль и белый фон."""
    root = ElementTree.Element("svg", {"xmlns": sheet_format.SVG_NS,
                                       "viewBox": f"0 0 {num(width)} {num(height)}"})
    ElementTree.SubElement(root, "style").text = css
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
    cells, width, height = _layout(sheet, cfg.sheet.sheet)
    mm_per_m = 1000 / cfg.sheet.sheet.scale
    root = canvas(width, height, cfg.css)
    root.set("width", f"{width * mm_per_m:.0f}mm")
    root.set("height", f"{height * mm_per_m:.0f}mm")
    pen = _pen(sheet, cfg)
    axes, levels = _axis_labels(sheet, cfg.sheet.axes.letters), _levels(sheet, cfg.sheet.levels)
    for facade, origin in zip(sheet.facades, cells, strict=True):
        g = _facade_geometry(root, facade, origin, pen)
        if violations is not None:
            _overlay(g, facade, [v for v in violations if v.side == facade.side.index])
        if annotations:
            marks = Marks(levels, axes[facade.side.index], cfg.sheet)
            _annotations(root, origin, facade.side.length_m, marks)
    ElementTree.indent(root)
    return ElementTree.tostring(root, encoding="unicode")


def _pen(sheet: FacadeSheet, cfg: Config) -> Pen:
    kinds = cfg.library.kinds
    colors = {}
    for m in sheet.spec.materials:
        if m.color is None and m.kind not in kinds:
            raise ValueError(f"материал {m.id}: нет цвета, и вида {m.kind} нет в библиотеке")
        colors[m.id] = m.color or kinds[m.kind]
    return Pen(cfg, colors)


def _top(facade: SideFacade) -> float:
    return max(y for _, y in facade.silhouette or [])


def _layout(sheet: FacadeSheet, lay: SheetLayout) -> tuple[list[tuple[float, float]], float, float]:
    """Фасады рядами по lay.columns; (ox, oy) — левый край стены и уровень земли."""
    col_w = max(f.side.length_m for f in sheet.facades) + lay.gap_x_m
    row_h = max(_top(f) for f in sheet.facades) + lay.gap_y_m
    cells = []
    for i, _ in enumerate(sheet.facades):
        row, col = divmod(i, lay.columns)
        ground = lay.margin_top_m + (row + 1) * row_h - lay.gap_y_m
        cells.append((lay.margin_left_m + col * col_w, ground))
    rows = math.ceil(len(sheet.facades) / lay.columns)
    return cells, lay.margin_left_m + lay.columns * col_w, lay.margin_top_m + rows * row_h


def _facade_geometry(root: ElementTree.Element, facade: SideFacade, origin,
                     pen: Pen) -> ElementTree.Element:
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
    for e in facade.elements:
        _element(g, e, pen)
    return g


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
        "fill": pen.colors[z.material],
    })


def _element(g: ElementTree.Element, e: Element, pen: Pen) -> None:
    lib = pen.cfg.library
    attrs = {
        sheet_format.CLS: e.cls, sheet_format.ID: e.id,
        "x": num(e.x_m), "y": num(e.y_m), "width": num(e.w_m), "height": num(e.h_m),
        "fill": pen.colors.get(e.material or "", lib.class_fill.get(e.cls, lib.fill.other)),
    }
    optional = {
        sheet_format.FLOOR: e.floor,
        sheet_format.PARENT: e.parent,
        sheet_format.MATERIAL: e.material,
    }
    attrs |= {k: str(v) for k, v in optional.items() if v is not None}
    if e.variant is not None:
        attrs[sheet_format.VARIANT] = sheet_format.encode_variant(e.variant)
    if e.fixed:
        attrs[sheet_format.FIXED] = ",".join(e.fixed)
    if e.cls is ElementClass.WINDOW:
        attrs["fill"] = lib.fill.glass  # материал окна красит раму
        if e.material:
            attrs["stroke"] = pen.colors[e.material]
    ElementTree.SubElement(g, "rect", attrs)
    if e.cls is ElementClass.WINDOW and e.variant is not None:
        _mullions(g, e)


def _mullions(g: ElementTree.Element, e: Element) -> None:
    """Деление рамы на створки — линии поверх стекла, в разбор не входят."""
    v = e.variant
    for x in (e.x_m + e.w_m * i / v.cols for i in range(1, v.cols)):
        add_line(g, "mullion", (x, e.y_m), (x, e.y_m + e.h_m))
    for y in (e.y_m + e.h_m * j / v.rows for j in range(1, v.rows)):
        add_line(g, "mullion", (e.x_m, y), (e.x_m + e.w_m, y))


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
        s.index: (label(corners[(k + 1) % 4], s), label(corners[k], s))
        for k, s in enumerate(sides)
    }


def _levels(sheet: FacadeSheet, cfg: Levels) -> list[float]:
    """Земля, цоколь, этажи, карниз — одни на все фасады дома."""
    spec = sheet.spec
    levels = [0.0, *spec.floor_levels(), spec.eaves_m]
    uniq: list[float] = []
    for v in sorted(levels):
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
        _level_mark(g, length + cfg.levels.offset_m, v, cfg.levels)
    for x, name in ((0.0, marks.axes[0]), (length, marks.axes[1])):
        _axis_bubble(g, x, name, cfg.axes)
    title = f"Фасад в осях {marks.axes[0]}–{marks.axes[1]}"
    add_text(g, "title", (length / 2, cfg.title.y_m), title)


def _level_mark(g: ElementTree.Element, x: float, level: float, cfg: Levels) -> None:
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
