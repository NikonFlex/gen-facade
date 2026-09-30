"""Зоны отделки стены (facade.md, MaterialZone): цоколь, основная, акцент, пояса.

Высоты цоколя, этажей и карниза — из HouseSpec, одни на дом: зоны соседних стен сходятся
на углах (facade.md, правило 9). Акцент — фронтон, а на стене без фронтона — полоса у входа.
"""

import shapely

from genfacade.config import LayoutRule
from genfacade.schema import EPS, Element, HouseSpec, MaterialZone, Polygon, SideFacade

ROLES = ("main", "plinth", "accent", "trim")


def palette_roles(spec: HouseSpec) -> dict[str, str]:
    """Роль → id материала палитры. Палитра правила шага 1 названа по ролям; у палитры,
    написанной руками, роли берутся по порядку, без материала крыши."""
    ids = [m.id for m in spec.materials if m.id != spec.roof.material] or [spec.materials[0].id]
    return {role: role if role in ids else ids[min(i, len(ids) - 1)]
            for i, role in enumerate(ROLES)}


def zones(wall: SideFacade, spec: HouseSpec, doors: list[Element],
          rule: LayoutRule) -> list[MaterialZone]:
    roles, length = palette_roles(spec), wall.side.length_m
    out = [
        MaterialZone(role="plinth", material=roles["plinth"],
                     shape=_rect(0, 0, length, spec.plinth_m)),
        MaterialZone(role="main", material=roles["main"],
                     shape=_rect(0, spec.plinth_m, length, spec.eaves_m)),
    ]
    gable = _above(wall.silhouette or [], spec.eaves_m)
    if gable:
        out.append(MaterialZone(role="accent", material=roles["accent"], shape=gable))
    elif doors:
        # полоса у входа — на ширину зазора, куда окна не ставятся: окно не заходит на акцент
        pad, d = rule.blind.clearance_m, doors[0]
        x0, x1 = max(0.0, d.x_m - pad), min(length, d.x_m + d.w_m + pad)
        out.append(MaterialZone(role="accent", material=roles["accent"],
                                shape=_rect(x0, spec.plinth_m, x1, spec.eaves_m)))
    half = rule.band.height_m / 2
    for level in spec.floor_levels()[1:-1]:  # перекрытия между этажами
        out.append(MaterialZone(role="band", material=roles["trim"],
                                shape=_rect(0, level - half, length, level + half)))
    return out


def _rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _above(silhouette: Polygon, y: float) -> Polygon | None:
    """Часть силуэта выше отметки — фронтон; нет её — None."""
    if len(silhouette) < 3:
        return None
    shape = shapely.Polygon(silhouette)
    x0, _, x1, top = shape.bounds
    part = shape.intersection(shapely.box(x0, y, x1, top))
    if part.is_empty or part.area < EPS:
        return None
    return [(float(x), float(py)) for x, py in part.exterior.coords[:-1]]
