"""SVG листа → элементы и зоны по сторонам: проверка, что SVG несёт всё из JSON."""

from xml.etree import ElementTree

from genfacade.render import sheet_format
from genfacade.schema import Element, MaterialZone


def parse_sheet_svg(text: str) -> dict[int, tuple[list[Element], list[MaterialZone]]]:
    """Сторона → (элементы, зоны) в том порядке, в каком они на листе."""
    # Разбираем только свой же лист, не чужие файлы — защита defusedxml не нужна.
    root = ElementTree.fromstring(text)  # noqa: S314
    result = {}
    # {*} — тег в любом пространстве имён: у листа оно SVG, и без этого g не найдётся.
    for g in root.findall(f"{{*}}g[@class='{sheet_format.FACADE_CLASS}']"):
        elements = [_element(r) for r in g.findall(f"{{*}}rect[@{sheet_format.CLS}]")]
        zones = [_zone(p) for p in g.findall(f"{{*}}polygon[@{sheet_format.ROLE}]")]
        result[int(g.get(sheet_format.SIDE))] = (elements, zones)
    return result


def _element(r: ElementTree.Element) -> Element:
    data = {
        "id": r.get(sheet_format.ID), "cls": r.get(sheet_format.CLS),
        "x_m": float(r.get("x")), "y_m": float(r.get("y")),
        "w_m": float(r.get("width")), "h_m": float(r.get("height")),
        "parent": r.get(sheet_format.PARENT), "material": r.get(sheet_format.MATERIAL),
    }
    if r.get(sheet_format.FLOOR) is not None:
        data["floor"] = int(r.get(sheet_format.FLOOR))
    if r.get(sheet_format.VARIANT):
        data["variant"] = sheet_format.decode_variant(r.get(sheet_format.VARIANT))
    if r.get(sheet_format.FIXED):
        data["fixed"] = r.get(sheet_format.FIXED).split(",")
    return Element(**data)


def _zone(p: ElementTree.Element) -> MaterialZone:
    pts = [tuple(float(c) for c in pair.split(",")) for pair in p.get("points").split()]
    material, role = p.get(sheet_format.MATERIAL), p.get(sheet_format.ROLE)
    return MaterialZone(shape=pts, material=material, role=role)
