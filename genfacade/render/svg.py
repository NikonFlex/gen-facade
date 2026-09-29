"""Шаг 6: лист фасадов в SVG (facade.md, правила 5–7).

Координаты — метры, лист в масштабе 1:100 (1 м = 10 мм). Каждый элемент и зона
несут в `data-*` всё, что есть в JSON, поэтому SVG разбирается обратно без потерь
(parse.py). Геометрия фасада — в группе с осью y вверх, подписи — в обычной.
"""

import math
import xml.etree.ElementTree as ET

from genfacade.schema import Element, FacadeSheet, MaterialZone, Polygon, SideFacade
from genfacade.unfold import plan_corners, ridge_height

SVG_NS = "http://www.w3.org/2000/svg"
GAP_X, GAP_Y = 5.0, 4.0  # поля между фасадами на листе: отметки справа, оси и подпись снизу
FONT = 0.3
DEFAULT_FILL = {
    "window": "#a9c4d8", "door": "#7b5230", "garage_door": "#d9d9d9",
    "sill": "#f0f0ee", "wall": "#e8e4dc", "roof": "#555a60",
}
LINE = "#2b2b2b"


def num(v: float) -> str:
    """Точное представление числа: разбор SVG должен вернуть то же значение."""
    return repr(float(v))


def points(poly: Polygon) -> str:
    return " ".join(f"{num(x)},{num(y)}" for x, y in poly)


def sheet_svg(sheet: FacadeSheet) -> str:
    """Лист всех фасадов; силуэты должны быть посчитаны (unfold)."""
    colors = {m.id: m.color for m in sheet.spec.materials}
    cells, width, height = _layout(sheet)
    root = ET.Element("svg", {
        "xmlns": SVG_NS, "viewBox": f"0 0 {num(width)} {num(height)}",
        "width": f"{width * 10:.0f}mm", "height": f"{height * 10:.0f}mm",
        "font-family": "Golos Text, DejaVu Sans, sans-serif", "font-size": num(FONT),
    })
    ET.SubElement(root, "rect", {"width": "100%", "height": "100%", "fill": "#ffffff"})
    axes, levels = _axis_labels(sheet), _levels(sheet)
    for facade, origin in zip(sheet.facades, cells, strict=True):
        _facade_geometry(root, facade, origin, colors | {"roof": _roof_color(sheet, colors)})
        _annotations(root, origin, facade.side.length_m, (levels, axes[facade.side.index]))
    ET.indent(root)
    return ET.tostring(root, encoding="unicode")


def _roof_color(sheet: FacadeSheet, colors: dict[str, str]) -> str:
    return colors.get(sheet.spec.roof.material or "", DEFAULT_FILL["roof"])


def _top(facade: SideFacade) -> float:
    return max(y for _, y in (facade.silhouette or []) + (facade.roof or []))


def _layout(sheet: FacadeSheet) -> tuple[list[tuple[float, float]], float, float]:
    """Два фасада в ряд; (ox, oy) — левый край стены и уровень земли на листе."""
    col_w = max(f.side.length_m for f in sheet.facades) + GAP_X
    row_h = max(_top(f) for f in sheet.facades) + GAP_Y
    cells = []
    for i, _ in enumerate(sheet.facades):
        row, col = divmod(i, 2)
        cells.append((2.0 + col * col_w, 1.5 + row * row_h + row_h - GAP_Y))
    rows = math.ceil(len(sheet.facades) / 2)
    return cells, 2.0 + 2 * col_w, 1.5 + rows * row_h


def _facade_geometry(root: ET.Element, facade: SideFacade, origin, colors) -> None:
    ox, oy = origin
    g = ET.SubElement(root, "g", {
        "class": "facade", "data-side": str(facade.side.index),
        "transform": f"translate({num(ox)},{num(oy)}) scale(1,-1)",
        "stroke": LINE, "stroke-width": "0.02", "stroke-linejoin": "round",
    })
    ET.SubElement(g, "polygon", {"class": "wall", "points": points(facade.silhouette or []),
                                 "fill": DEFAULT_FILL["wall"]})
    for z in facade.zones:
        _zone(g, z, colors)
    # Контур до крыши: свес закрывает верх стены, линия карниза не должна просвечивать.
    ET.SubElement(g, "polygon", {"class": "outline", "points": points(facade.silhouette or []),
                                 "fill": "none", "stroke-width": "0.04"})
    if facade.roof:
        ET.SubElement(g, "polygon", {"class": "roof", "points": points(facade.roof),
                                     "fill": colors["roof"]})
    for e in facade.elements:
        _element(g, e, colors)


def _zone(g: ET.Element, z: MaterialZone, colors: dict[str, str]) -> None:
    ET.SubElement(g, "polygon", {
        "data-role": z.role, "data-material": z.material, "points": points(z.shape),
        "fill": colors[z.material], "stroke": "none",
    })


def _element(g: ET.Element, e: Element, colors: dict[str, str]) -> None:
    attrs = {
        "data-cls": e.cls, "data-id": e.id,
        "x": num(e.x_m), "y": num(e.y_m), "width": num(e.w_m), "height": num(e.h_m),
        "fill": colors.get(e.material or "", DEFAULT_FILL.get(e.cls, "#bdbdbd")),
    }
    optional = {"data-floor": e.floor, "data-parent": e.parent, "data-material": e.material}
    attrs |= {k: str(v) for k, v in optional.items() if v is not None}
    if e.variant is not None:
        attrs["data-variant"] = f"{e.variant.kind}:{e.variant.cols}:{e.variant.rows}"
    if e.fixed:
        attrs["data-fixed"] = ",".join(e.fixed)
    if e.cls == "window":
        attrs["fill"] = DEFAULT_FILL["window"]  # стекло; материал элемента — рама
        attrs["stroke"] = colors.get(e.material or "", LINE)
        attrs["stroke-width"] = "0.06"
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
                                  "x2": num(x2), "y2": num(y2), "stroke-width": "0.04"})


def _axis_labels(sheet: FacadeSheet) -> dict[int, tuple[str, str]]:
    """Оси на краях каждого фасада, как в эскизном проекте: 1, 2… по x, А, Б… по y.

    Сторона i идёт от угла i к углу i+1 по часовой; снаружи её левый край — угол i+1.
    """
    sides = [f.side for f in sheet.facades]
    corners = plan_corners(sides)
    xs = sorted({round(x, 6) for x, _ in corners})
    ys = sorted({round(y, 6) for _, y in corners})
    letters = "АБВГДЕЖИКЛМН"

    def label(corner, side) -> str:
        if abs(side.orientation[1]) > 0.5:  # стена вдоль x — цифровые оси
            return str(xs.index(round(corner[0], 6)) + 1)
        return letters[ys.index(round(corner[1], 6))]

    return {
        s.index: (label(corners[(k + 1) % 4], s), label(corners[k], s))
        for k, s in enumerate(sides)
    }


def _levels(sheet: FacadeSheet) -> list[float]:
    """Земля, цоколь, этажи, карниз, конёк — одни на все фасады дома."""
    spec = sheet.spec
    levels = [0.0, *spec.floor_levels(), spec.eaves_m]
    levels.append(ridge_height(spec, [f.side for f in sheet.facades]))
    uniq: list[float] = []
    for v in sorted(levels):
        if not uniq or v - uniq[-1] > 0.05:
            uniq.append(v)
    return uniq


def _annotations(root: ET.Element, origin, length: float, marks) -> None:
    """Линия земли, отметки уровней справа, оси по краям, подпись снизу."""
    ox, oy = origin
    levels, axes = marks
    g = ET.SubElement(root, "g", {"class": "annotations", "transform":
                                  f"translate({num(ox)},{num(oy)})", "stroke": LINE,
                                  "stroke-width": "0.015", "fill": LINE})
    ET.SubElement(g, "line", {"class": "ground", "x1": "-1.5", "y1": "0",
                              "x2": num(length + 1.5), "y2": "0", "stroke-width": "0.05"})
    for v in levels:
        _level_mark(g, length + 1.2, v)
    for x, name in ((0.0, axes[0]), (length, axes[1])):
        _axis_bubble(g, x, name)
    title = f"Фасад в осях {axes[0]}–{axes[1]}"
    t = ET.SubElement(g, "text", {"x": num(length / 2), "y": "2.6", "text-anchor": "middle",
                                  "stroke": "none", "font-size": num(FONT * 1.4)})
    t.text = title


def _level_mark(g: ET.Element, x: float, level: float) -> None:
    """Отметка уровня: треугольник на полке и значение над ней, «+3,300»."""
    y = -level
    ET.SubElement(g, "line", {"x1": num(x - 0.9), "y1": num(y), "x2": num(x + 1.4), "y2": num(y)})
    marker = [(x, y), (x - 0.15, y - 0.2), (x + 0.15, y - 0.2)]
    ET.SubElement(g, "polygon", {"points": points(marker), "fill": "none"})
    ground = abs(level) < 1e-9
    # Земля подписана под полкой: цоколь бывает ниже высоты шрифта, подписи слиплись бы.
    ty = y + FONT if ground else y - 0.06
    t = ET.SubElement(g, "text", {"x": num(x + 0.25), "y": num(ty), "stroke": "none",
                                  "font-size": num(FONT * 0.9)})
    sign = "±" if ground else "+"
    t.text = f"{sign}{level:.3f}".replace(".", ",")


def _axis_bubble(g: ET.Element, x: float, name: str) -> None:
    ET.SubElement(g, "line", {"x1": num(x), "y1": "0.1", "x2": num(x), "y2": "1.2",
                              "stroke-dasharray": "0.15 0.1"})
    ET.SubElement(g, "circle", {"cx": num(x), "cy": "1.6", "r": "0.4", "fill": "none"})
    t = ET.SubElement(g, "text", {"x": num(x), "y": "1.71", "text-anchor": "middle",
                                  "stroke": "none"})
    t.text = name
