"""Примитивы SVG листа: линия, прямоугольник, многоугольник — общие для листа (svg.py) и рисунка
выводимых элементов (trim.py). Координаты — метры натуры, как на листе."""

from xml.etree import ElementTree

from genfacade.render.sheet_format import num
from genfacade.schema import Point, Polygon


def points(poly: Polygon) -> str:
    return " ".join(f"{num(x)},{num(y)}" for x, y in poly)


def add_line(g: ElementTree.Element, css_class: str, start: Point, end: Point) -> None:
    (x1, y1), (x2, y2) = start, end
    ElementTree.SubElement(g, "line", {"class": css_class, "x1": num(x1), "y1": num(y1),
                                       "x2": num(x2), "y2": num(y2)})


def box(g: ElementTree.Element, css_class: str, rect: tuple[float, ...]) -> ElementTree.Element:
    x, y, w, h = rect
    return ElementTree.SubElement(g, "rect", {"class": css_class, "x": num(x), "y": num(y),
                                              "width": num(w), "height": num(h)})
