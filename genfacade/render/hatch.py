"""Рисунок вида материала на листе: SVG `<pattern>` в метрах фасада (gf#304,
`facade: Рисунок материала`).

Рисунок — часть оформления листа, JSON он не меняет. Паттерн один на пару вид × цвет: цвет
линий считается из цвета материала (темнее), поэтому два кирпича разного цвета — два паттерна.
`patternUnits="userSpaceOnUse"` — рисунок лежит в системе координат фасада: ряды идут от земли,
шаг — метры натуры, а не доля зоны.
"""

import re
from xml.etree import ElementTree

from genfacade.config import Hatch
from genfacade.render.sheet_format import num

PRECISION = 6  # знаков в метрах: суммы шагов не оставляют хвостов float в SVG
HEX = re.compile(r"#[0-9a-fA-F]{6}")


def darken(color: str, k: float) -> str:
    """Цвет #rrggbb темнее: каждый канал × (1 − k)."""
    if not HEX.fullmatch(color):
        raise ValueError(f"цвет материала {color!r} — не #rrggbb: линии рисунка не посчитать")
    channels = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(c * (1 - k)):02x}" for c in channels)


def pattern_id(kind: str, color: str) -> str:
    return f"hatch-{kind}-{color.lstrip('#').lower()}"


def pattern(kind: str, hatch: Hatch, color: str, darkening: float) -> ElementTree.Element:
    """`<pattern>`: фон цвета материала и линии швов; id — pattern_id(kind, color)."""
    height = round(sum(c.h_m for c in hatch.courses), PRECISION)
    size = (height, hatch.width_m) if hatch.vertical else (hatch.width_m, height)
    node = ElementTree.Element("pattern", {
        "id": pattern_id(kind, color), "patternUnits": "userSpaceOnUse",
        "width": num(size[0]), "height": num(size[1])})
    ElementTree.SubElement(node, "rect", {"width": num(size[0]), "height": num(size[1]),
                                          "fill": color})
    ElementTree.SubElement(node, "path", {
        "d": " ".join(f"M{num(x1)},{num(y1)}L{num(x2)},{num(y2)}"
                      for (x1, y1), (x2, y2) in _segments(hatch)),
        "fill": "none", "stroke": darken(color, darkening), "stroke-width": num(hatch.line_m)})
    return node


def _segments(hatch: Hatch) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Швы в осях «ряд — поперёк ряда»; у повёрнутого рисунка оси меняются местами."""
    half, out, y = hatch.line_m / 2, [], 0.0
    for course in hatch.courses:
        # Линия лежит целиком внутри ячейки: на её краю половина толщины обрезалась бы
        edge = y + half
        out.append(((0.0, edge), (hatch.width_m, edge)))
        if hatch.groove_m:
            out.append(((0.0, edge + hatch.groove_m), (hatch.width_m, edge + hatch.groove_m)))
        out += [((x, y), (x, y + course.h_m)) for x in course.joints_m]
        y += course.h_m
    if hatch.vertical:
        out = [((y1, x1), (y2, x2)) for (x1, y1), (x2, y2) in out]
    return [tuple((round(x, PRECISION), round(y, PRECISION)) for x, y in seg) for seg in out]
