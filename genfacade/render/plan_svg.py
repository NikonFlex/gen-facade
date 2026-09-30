"""Трасса шага 2: план после препроцессора — стены, контур, стороны, проёмы, запретные зоны.

Не чертёж для сдачи, а картинка для проверки глазами: номера сторон с длинами, вход,
заделанные в глухом режиме разрывы, запретные зоны у сторон. Оформление — config/sheet.toml
([plan]) и config/sheet.css (.plan-*).
"""

import math
from xml.etree import ElementTree

from genfacade.config import Config, PlanLook
from genfacade.render.sheet_format import num
from genfacade.render.svg import add_line, canvas, points
from genfacade.schema import Plan, Point, Rect, Side

LEGEND = ("вход — зелёный, окно — голубой, дверь — коричневый,",
          "заделан — оранжевый, запретная зона — красный")


def plan_svg(plan: Plan, cfg: Config) -> str:
    look = cfg.sheet.plan
    xs, ys = [p[0] for p in plan.outline], [p[1] for p in plan.outline]
    x0, top = min(xs) - look.margin_m, max(ys) + look.margin_m
    width, height = max(xs) + look.margin_m - x0, top - (min(ys) - look.margin_m)
    root = canvas(width, height, cfg.css)
    g = ElementTree.SubElement(root, "g", {
        "transform": f"translate({num(-x0)},{num(top)}) scale(1,-1)"})
    for w in plan.walls:
        _rect(g, w, "plan-wall")
    for o in plan.openings:
        _rect(g, o.rect, "plan-sealed" if o.sealed else f"plan-{o.kind}")
    ElementTree.SubElement(g, "polygon", {"class": "plan-outline", "points": points(plan.outline)})
    for side in plan.sides:
        _forbidden(g, plan.outline, side, look.forbidden_inset_m)
        _label(root, _side_label_at(plan.outline, side, look.label_offset_m), (x0, top), side)
    _legend(root, height, look)
    return ElementTree.tostring(root, encoding="unicode")


def _legend(root: ElementTree.Element, height: float, look: PlanLook) -> None:
    for i, line in enumerate(reversed(LEGEND)):
        y = height - look.legend_margin_m - look.legend_line_m * i
        node = ElementTree.SubElement(root, "text", {"class": "plan-legend",
                                                     "x": num(look.legend_margin_m), "y": num(y)})
        node.text = line


def _rect(g: ElementTree.Element, r: Rect, css_class: str) -> None:
    ElementTree.SubElement(g, "rect", {
        "class": css_class, "x": num(r.x0_m), "y": num(r.y0_m),
        "width": num(r.x1_m - r.x0_m), "height": num(r.y1_m - r.y0_m)})


def _along(outline: list[Point], side: Side, x_m: float, inset: float) -> Point:
    """Точка стороны на расстоянии x_m от её левого края (снаружи), сдвинутая внутрь."""
    p = outline[side.index]
    q = outline[(side.index + 1) % len(outline)]
    t = (side.length_m - x_m) / side.length_m
    nx, ny = side.orientation
    return (p[0] + (q[0] - p[0]) * t - nx * inset, p[1] + (q[1] - p[1]) * t - ny * inset)


def _forbidden(g: ElementTree.Element, outline: list[Point], side: Side, inset: float) -> None:
    for z in side.forbidden:
        add_line(g, "plan-forbidden", _along(outline, side, z.x0_m, inset),
                 _along(outline, side, z.x1_m, inset))


def _side_label_at(outline: list[Point], side: Side, offset: float) -> Point:
    return _along(outline, side, side.length_m / 2, -offset)


def _label(root: ElementTree.Element, at: Point, origin: Point, side: Side) -> None:
    (x, y), (x0, top) = at, origin
    node = ElementTree.SubElement(root, "text", {"class": "plan-label", "x": num(x - x0),
                                                 "y": num(top - y)})
    entrance = " · вход" if side.has_entrance else ""
    node.text = f"{side.index}: {side.length_m:.2f} м{entrance}"
    if math.isclose(side.orientation[0], 0):
        return
    # на вертикальной стороне подпись поворачиваем вдоль неё
    node.set("transform", f"rotate(-90 {num(x - x0)} {num(top - y)})")
