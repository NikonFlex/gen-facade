"""Шаг 6: лист фасадов в SVG (facade.md, правила 5–7).

Координаты — метры натуры; оформление — config/sheet.toml (размеры) и
config/sheet.css (линии, шрифты), заливки по умолчанию — config/library.toml.
Каждый элемент и зона несут в `data-*` всё, что есть в JSON (format.py), поэтому
SVG разбирается обратно без потерь. Геометрия фасада — в группе с осью y вверх,
подписи — в обычной.
"""

import math
import xml.etree.ElementTree as ET
from typing import NamedTuple

from genfacade.config import Axes, Config, Levels, Sheet, SheetLayout
from genfacade.render import format as fmt
from genfacade.render.format import num
from genfacade.schema import EPS, Element, FacadeSheet, MaterialZone, Polygon, SideFacade
from genfacade.unfold import plan_corners, ridge_height


class Pen(NamedTuple):
    """Чем красить: настройки и цвета материалов этого дома."""

    cfg: Config
    colors: dict[str, str]  # id материала палитры → цвет
    roof: str


class Marks(NamedTuple):
    """Подписи одного фасада."""

    levels: list[float]
    axes: tuple[str, str]  # левая и правая ось, если смотреть снаружи
    sheet: Sheet


def points(poly: Polygon) -> str:
    return " ".join(f"{num(x)},{num(y)}" for x, y in poly)


def sheet_svg(sheet: FacadeSheet, cfg: Config) -> str:
    """Лист всех фасадов; силуэты должны быть посчитаны (unfold)."""
    cells, width, height = _layout(sheet, cfg.sheet.sheet)
    mm_per_m = 1000 / cfg.sheet.sheet.scale
    root = ET.Element("svg", {
        "xmlns": fmt.SVG_NS, "viewBox": f"0 0 {num(width)} {num(height)}",
        "width": f"{width * mm_per_m:.0f}mm", "height": f"{height * mm_per_m:.0f}mm",
    })
    ET.SubElement(root, "style").text = cfg.css
    ET.SubElement(root, "rect", {"class": "background", "width": "100%", "height": "100%"})
    pen = _pen(sheet, cfg)
    axes, levels = _axis_labels(sheet, cfg.sheet.axes.letters), _levels(sheet, cfg.sheet.levels)
    for facade, origin in zip(sheet.facades, cells, strict=True):
        _facade_geometry(root, facade, origin, pen)
        marks = Marks(levels, axes[facade.side.index], cfg.sheet)
        _annotations(root, origin, facade.side.length_m, marks)
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


def _pen(sheet: FacadeSheet, cfg: Config) -> Pen:
    kinds = cfg.library.kinds
    colors = {}
    for m in sheet.spec.materials:
        if m.color is None and m.kind not in kinds:
            raise ValueError(f"материал {m.id}: нет цвета, и вида {m.kind} нет в библиотеке")
        colors[m.id] = m.color or kinds[m.kind]
    roof = colors.get(sheet.spec.roof.material or "", cfg.library.fill.roof)
    return Pen(cfg, colors, roof)


def _top(facade: SideFacade) -> float:
    return max(y for _, y in (facade.silhouette or []) + (facade.roof or []))


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


def _facade_geometry(root: ET.Element, facade: SideFacade, origin, pen: Pen) -> None:
    ox, oy = origin
    g = ET.SubElement(root, "g", {
        "class": fmt.FACADE_CLASS, fmt.SIDE: str(facade.side.index),
        "transform": f"translate({num(ox)},{num(oy)}) scale(1,-1)",
    })
    silhouette = points(facade.silhouette or [])
    ET.SubElement(g, "polygon", {"class": "wall", "points": silhouette,
                                 "fill": pen.cfg.library.fill.wall})
    for z in facade.zones:
        _zone(g, z, pen)
    # Контур до крыши: свес закрывает верх стены, линия карниза не должна просвечивать.
    ET.SubElement(g, "polygon", {"class": "outline", "points": silhouette})
    if facade.roof:
        ET.SubElement(g, "polygon", {"class": "roof", "points": points(facade.roof),
                                     "fill": pen.roof})
    for e in facade.elements:
        _element(g, e, pen)


def _zone(g: ET.Element, z: MaterialZone, pen: Pen) -> None:
    ET.SubElement(g, "polygon", {
        fmt.ROLE: z.role, fmt.MATERIAL: z.material, "points": points(z.shape),
        "fill": pen.colors[z.material],
    })


def _element(g: ET.Element, e: Element, pen: Pen) -> None:
    lib = pen.cfg.library
    attrs = {
        fmt.CLS: e.cls, fmt.ID: e.id,
        "x": num(e.x_m), "y": num(e.y_m), "width": num(e.w_m), "height": num(e.h_m),
        "fill": pen.colors.get(e.material or "", lib.class_fill.get(e.cls, lib.fill.other)),
    }
    optional = {fmt.FLOOR: e.floor, fmt.PARENT: e.parent, fmt.MATERIAL: e.material}
    attrs |= {k: str(v) for k, v in optional.items() if v is not None}
    if e.variant is not None:
        attrs[fmt.VARIANT] = fmt.encode_variant(e.variant)
    if e.fixed:
        attrs[fmt.FIXED] = ",".join(e.fixed)
    if e.cls == "window":
        attrs["fill"] = lib.fill.glass  # материал окна красит раму
        if e.material:
            attrs["stroke"] = pen.colors[e.material]
    ET.SubElement(g, "rect", attrs)
    if e.cls == "window" and e.variant is not None:
        _mullions(g, e)


def _mullions(g: ET.Element, e: Element) -> None:
    """Деление рамы на створки — линии поверх стекла, в разбор не входят."""
    v = e.variant
    cuts = [("x", e.x_m + e.w_m * i / v.cols) for i in range(1, v.cols)]
    cuts += [("y", e.y_m + e.h_m * j / v.rows) for j in range(1, v.rows)]
    for axis, c in cuts:
        x1, y1, x2, y2 = (c, e.y_m, c, e.y_m + e.h_m) if axis == "x" else (
            e.x_m, c, e.x_m + e.w_m, c)
        ET.SubElement(g, "line", {"class": "mullion", "x1": num(x1), "y1": num(y1),
                                  "x2": num(x2), "y2": num(y2)})


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
    """Земля, цоколь, этажи, карниз, конёк — одни на все фасады дома."""
    spec = sheet.spec
    levels = [0.0, *spec.floor_levels(), spec.eaves_m]
    levels.append(ridge_height(spec, [f.side for f in sheet.facades]))
    uniq: list[float] = []
    for v in sorted(levels):
        if not uniq or v - uniq[-1] > cfg.merge_below_m:
            uniq.append(v)
    return uniq


def _annotations(root: ET.Element, origin, length: float, marks: Marks) -> None:
    """Линия земли, отметки уровней справа, оси по краям, подпись снизу."""
    ox, oy = origin
    cfg = marks.sheet
    g = ET.SubElement(root, "g", {"class": "annotations",
                                  "transform": f"translate({num(ox)},{num(oy)})"})
    ext = cfg.ground.extend_m
    ET.SubElement(g, "line", {"class": "ground", "x1": num(-ext), "y1": "0",
                              "x2": num(length + ext), "y2": "0"})
    for v in marks.levels:
        _level_mark(g, length + cfg.levels.offset_m, v, cfg.levels)
    for x, name in ((0.0, marks.axes[0]), (length, marks.axes[1])):
        _axis_bubble(g, x, name, cfg.axes)
    t = ET.SubElement(g, "text", {"class": "title", "x": num(length / 2), "y": num(cfg.title.y_m)})
    t.text = f"Фасад в осях {marks.axes[0]}–{marks.axes[1]}"


def _level_mark(g: ET.Element, x: float, level: float, cfg: Levels) -> None:
    """Отметка уровня: треугольник на полке и значение над ней, «+3,300»."""
    y = -level
    ET.SubElement(g, "line", {"class": "level-shelf", "x1": num(x - cfg.shelf_left_m),
                              "y1": num(y), "x2": num(x + cfg.shelf_right_m), "y2": num(y)})
    half, height = cfg.marker_half_width_m, cfg.marker_height_m
    marker = [(x, y), (x - half, y - height), (x + half, y - height)]
    ET.SubElement(g, "polygon", {"class": "level-marker", "points": points(marker)})
    ground = level == 0.0
    # Земля подписана под полкой: цоколь бывает ниже высоты шрифта, подписи слиплись бы.
    ty = y + cfg.text_below_m if ground else y - cfg.text_above_m
    t = ET.SubElement(g, "text", {"class": "level-text", "x": num(x + cfg.text_dx_m),
                                  "y": num(ty)})
    t.text = f"{'±' if ground else '+'}{level:.3f}".replace(".", ",")


def _axis_bubble(g: ET.Element, x: float, name: str, cfg: Axes) -> None:
    ET.SubElement(g, "line", {"class": "axis-line", "x1": num(x), "y1": num(cfg.line_from_m),
                              "x2": num(x), "y2": num(cfg.line_to_m)})
    ET.SubElement(g, "circle", {"class": "axis-bubble", "cx": num(x),
                                "cy": num(cfg.bubble_y_m), "r": num(cfg.bubble_radius_m)})
    t = ET.SubElement(g, "text", {"class": "axis-text", "x": num(x),
                                  "y": num(cfg.bubble_y_m + cfg.text_dy_m)})
    t.text = name
