"""Контур окна по его виду (gf#319, `docs/decisions.md`, 08.11): форма окна — вид проёма
(`VariantKind`), рамка остаётся прямоугольником во всём модуле, контур считает этот модуль — для
листа, дома объёмом и проверки ската.

- `arch` — полукруглый верх: полуэллипс шириной рамки и высотой не больше половины ширины над
  прямоугольником (при высоте рамки в половину ширины — полукруглое окно);
- `oval` — эллипс, вписанный в рамку (круг при равных сторонах);
- `slope` — верх по скату: рамка, срезанная скатом с отступом `slope_offset_m` (трапеция или
  пятиугольник у конька); не во фронтоне — рамка;
- остальные виды — рамка.
"""

import math

import shapely

from genfacade import roof
from genfacade.schema import Element, Polygon, VariantKind

ARC_POINTS = 12  # точек на полуокружность: на листе 1:100 дуга без изломов


def kind(e: Element) -> VariantKind:
    return e.variant.kind if e.variant is not None else VariantKind.REGULAR


def outline(e: Element, gable: shapely.Geometry | None = None) -> Polygon:
    """Контур окна в метрах стены; gable — место окна во фронтоне (`roof.room`) или None."""
    x0, y0, x1, y1 = e.x_m, e.y_m, e.x_m + e.w_m, e.y_m + e.h_m
    box = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    match kind(e):
        case VariantKind.ARCH:
            r = min(e.h_m, e.w_m / 2)
            return [(x0, y0), (x1, y0), *_arc((x0 + x1) / 2, y1 - r, e.w_m / 2, r, 0, math.pi)]
        case VariantKind.OVAL:
            return _arc((x0 + x1) / 2, (y0 + y1) / 2, e.w_m / 2, e.h_m / 2, 0, 2 * math.pi)[:-1]
        case VariantKind.SLOPE if gable is not None:
            cut = shapely.box(x0, y0, x1, y1).intersection(gable)
            parts = getattr(cut, "geoms", [cut])
            best = max(parts, key=lambda g: g.area, default=None)
            if best is None or best.area <= 0 or best.geom_type != "Polygon":
                return box
            return list(best.exterior.coords)[:-1]
    return box


def gable_room(length: float, eaves: float, above: Polygon | None,
               offset: float) -> shapely.Geometry | None:
    """Место окна во фронтоне стены или None, если фронтона нет."""
    return None if above is None else roof.room(length, eaves, above, offset)


def _arc(cx: float, cy: float, rx: float, ry: float, start: float, end: float) -> Polygon:
    steps = max(2, round(ARC_POINTS * abs(end - start) / math.pi))
    return [(cx + rx * math.cos(start + (end - start) * i / steps),
             cy + ry * math.sin(start + (end - start) * i / steps)) for i in range(steps + 1)]
