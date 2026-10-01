"""Зоны отделки стены (facade.md, MaterialZone): цоколь, основная и акцент по схеме дома.

Высоты цоколя, карниза и нижнего пояса — одни на дом: зоны соседних стен сходятся на углах
(facade.md, правило 9).
"""

from genfacade.config import Finish
from genfacade.datasets.synthetic.house import Look, Scheme
from genfacade.schema import (
    Element,
    ElementClass,
    HouseSpec,
    MaterialZone,
    PaletteRole,
    Polygon,
    SideFacade,
    ZoneRole,
)

Box = tuple[float, float, float, float]  # x0, y0, x1, y1


def zones(wall: SideFacade, spec: HouseSpec, look: Look, cfg: Finish) -> list[MaterialZone]:
    """Зоны стены по её проёмам (`wall.elements`) и схеме отделки дома."""
    length = wall.side.length_m
    base = [
        _zone(ZoneRole.PLINTH, PaletteRole.PLINTH, (0, 0, length, spec.plinth_m)),
        _zone(ZoneRole.MAIN, PaletteRole.MAIN, (0, spec.plinth_m, length, spec.eaves_m)),
    ]
    return base + [_zone(ZoneRole.ACCENT, PaletteRole.ACCENT, box)
                   for box in _accents(wall, spec, look, cfg)]


def _accents(wall: SideFacade, spec: HouseSpec, look: Look, cfg: Finish) -> list[Box]:
    length, low, top = wall.side.length_m, spec.plinth_m, spec.eaves_m
    if look.scheme is Scheme.ENTRANCE:
        pad = cfg.entrance_pad_m
        return [(max(0.0, d.x_m - pad), low, min(length, d.x_m + d.w_m + pad), top)
                for d in _of(wall, ElementClass.DOOR)]
    if look.scheme is Scheme.WAINSCOT:
        return [(0.0, low, length, low + look.wainscot_m)]
    if look.scheme is Scheme.CORNERS:
        return [(0.0, low, cfg.corner_m, top), (length - cfg.corner_m, low, length, top)]
    if look.scheme is Scheme.PIERS:
        return _piers(_of(wall, ElementClass.WINDOW), cfg.pier_max_m)
    return []


def _piers(windows: list[Element], max_m: float) -> list[Box]:
    """Вставка в простенке между соседними окнами — на высоту большего из них."""
    row = sorted(windows, key=lambda w: w.x_m)
    return [
        (a.x_m + a.w_m, min(a.y_m, b.y_m), b.x_m, max(a.y_m + a.h_m, b.y_m + b.h_m))
        for a, b in zip(row, row[1:], strict=False) if b.x_m - (a.x_m + a.w_m) <= max_m
    ]


def _of(wall: SideFacade, cls: ElementClass) -> list[Element]:
    return [e for e in wall.elements if e.cls is cls]


def _zone(role: ZoneRole, material: PaletteRole, box: Box) -> MaterialZone:
    x0, y0, x1, y1 = box
    shape: Polygon = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return MaterialZone(role=role, material=material, shape=shape)
