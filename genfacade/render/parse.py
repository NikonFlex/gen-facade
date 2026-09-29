"""SVG листа → элементы и зоны по сторонам: проверка, что SVG несёт всё из JSON."""

import xml.etree.ElementTree as ET

from genfacade.render import format as fmt
from genfacade.schema import Element, MaterialZone

NS = {"svg": fmt.SVG_NS}


def parse_sheet_svg(text: str) -> dict[int, tuple[list[Element], list[MaterialZone]]]:
    """Сторона → (элементы, зоны) в том порядке, в каком они на листе."""
    # Разбираем только свой же лист, не чужие файлы — защита defusedxml не нужна.
    root = ET.fromstring(text)  # noqa: S314
    result = {}
    for g in root.findall(f"svg:g[@class='{fmt.FACADE_CLASS}']", NS):
        elements = [_element(r) for r in g.findall(f"svg:rect[@{fmt.CLS}]", NS)]
        zones = [_zone(p) for p in g.findall(f"svg:polygon[@{fmt.ROLE}]", NS)]
        result[int(g.get(fmt.SIDE))] = (elements, zones)
    return result


def _element(r: ET.Element) -> Element:
    data = {
        "id": r.get(fmt.ID), "cls": r.get(fmt.CLS),
        "x_m": float(r.get("x")), "y_m": float(r.get("y")),
        "w_m": float(r.get("width")), "h_m": float(r.get("height")),
        "parent": r.get(fmt.PARENT), "material": r.get(fmt.MATERIAL),
    }
    if r.get(fmt.FLOOR) is not None:
        data["floor"] = int(r.get(fmt.FLOOR))
    if r.get(fmt.VARIANT):
        data["variant"] = fmt.decode_variant(r.get(fmt.VARIANT))
    if r.get(fmt.FIXED):
        data["fixed"] = r.get(fmt.FIXED).split(",")
    return Element(**data)


def _zone(p: ET.Element) -> MaterialZone:
    pts = [tuple(float(c) for c in pair.split(",")) for pair in p.get("points").split()]
    return MaterialZone(shape=pts, material=p.get(fmt.MATERIAL), role=p.get(fmt.ROLE))
