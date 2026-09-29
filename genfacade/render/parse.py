"""SVG листа → элементы и зоны по сторонам: проверка, что SVG несёт всё из JSON."""

import xml.etree.ElementTree as ET

from genfacade.render.svg import SVG_NS
from genfacade.schema import Element, MaterialZone, OpeningVariant

NS = {"svg": SVG_NS}


def parse_sheet_svg(text: str) -> dict[int, tuple[list[Element], list[MaterialZone]]]:
    """Сторона → (элементы, зоны) в том порядке, в каком они на листе."""
    # Разбираем только свой же лист, не чужие файлы — защита defusedxml не нужна.
    root = ET.fromstring(text)  # noqa: S314
    result = {}
    for g in root.findall("svg:g[@class='facade']", NS):
        elements = [_element(r) for r in g.findall("svg:rect[@data-cls]", NS)]
        zones = [_zone(p) for p in g.findall("svg:polygon[@data-role]", NS)]
        result[int(g.get("data-side"))] = (elements, zones)
    return result


def _element(r: ET.Element) -> Element:
    data = {
        "id": r.get("data-id"), "cls": r.get("data-cls"),
        "x_m": float(r.get("x")), "y_m": float(r.get("y")),
        "w_m": float(r.get("width")), "h_m": float(r.get("height")),
        "parent": r.get("data-parent"), "material": r.get("data-material"),
    }
    if r.get("data-floor") is not None:
        data["floor"] = int(r.get("data-floor"))
    if r.get("data-variant"):
        kind, cols, rows = r.get("data-variant").split(":")
        data["variant"] = OpeningVariant(kind=kind, cols=int(cols), rows=int(rows))
    if r.get("data-fixed"):
        data["fixed"] = r.get("data-fixed").split(",")
    return Element(**data)


def _zone(p: ET.Element) -> MaterialZone:
    pts = [tuple(float(c) for c in pair.split(",")) for pair in p.get("points").split()]
    return MaterialZone(shape=pts, material=p.get("data-material"), role=p.get("data-role"))
