"""Зоны отделки стены (facade.md, MaterialZone): цоколь, основная, акцент у входа.

Высоты цоколя и карниза — из HouseSpec, одни на дом: зоны соседних стен сходятся на углах
(facade.md, правило 9).
"""

from genfacade.config import Accent
from genfacade.schema import Element, HouseSpec, MaterialZone, PaletteRole, Polygon, ZoneRole


def zones(length_m: float, spec: HouseSpec, accent_at: list[Element],
          accent: Accent) -> list[MaterialZone]:
    """accent_at — двери, у которых идёт акцентная полоса; пусто — полосы нет."""
    out = [
        MaterialZone(role=ZoneRole.PLINTH, material=PaletteRole.PLINTH,
                     shape=_rect(0, 0, length_m, spec.plinth_m)),
        MaterialZone(role=ZoneRole.MAIN, material=PaletteRole.MAIN,
                     shape=_rect(0, spec.plinth_m, length_m, spec.eaves_m)),
    ]
    for d in accent_at:
        x0, x1 = max(0.0, d.x_m - accent.pad_m), min(length_m, d.x_m + d.w_m + accent.pad_m)
        out.append(MaterialZone(role=ZoneRole.ACCENT, material=PaletteRole.ACCENT,
                                shape=_rect(x0, spec.plinth_m, x1, spec.eaves_m)))
    return out


def _rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
