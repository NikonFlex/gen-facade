"""Шаг 5: карниз, цоколь и низ двери — на отметки параметров дома (gf#272,
`facade: Высоты цоколя и карниза — из параметров`, `facade: Нуль отметок — земля`).

Параметры дома одни на все стены, а модель шага 4 ставит эти уровни на каждой стене по-своему:
карниз куском посреди стены и ниже отметки карниза, цоколь на одной стене из четырёх и выше
отметки цоколя, дверь на 1,85 м при поле 0,76 (листы проверки gf#268). Поэтому их ставит код:
- дверь — низ на полу своего этажа (`floor_levels`), высота та же, но с козырьком не выше
  отметки карниза; козырёк едет с ней (follow.py) и пропадает, если налез на чужой проём, как в
  derive.py; крыльцо — от земли до её низа. Гаражные ворота стоят на земле, их не трогаем;
- карниз — во всю стену, верх на `eaves_m`, высота — как у карниза модели на этой стене (у
  нескольких кусков — медиана), низ не ниже верха проёмов; стене без карниза он не добавляется —
  у настоящих домов карниз бывает только на части стен;
- цоколь — если он у дома есть (`plinth_m > 0` и модель поставила его хоть на одной стене) — на
  всех стенах от земли до `plinth_m`, материал — самый частый у цоколя модели. У 9 из 27 настоящих
  домов реального теста `plinth_m > 0` (пол поднят), а зоны цоколя нет — её не добавляем, если
  модель её не ставила. Зона «цоколь» модели до самого карниза — основная отделка, а не цоколь;
- остальные зоны модели упираются в края дверей, карниза и цоколя (`validate._anchored`): эти
  края едут на новые отметки вместе с ними, а что ниже верха цоколя — поднимается до него.
"""

from collections import Counter
from statistics import median
from typing import NamedTuple

from genfacade.config import Checks
from genfacade.derive import TRIM_OF, hits
from genfacade.follow import box, follow
from genfacade.schema import (
    EPS,
    OPENINGS,
    Element,
    ElementClass,
    FacadeSheet,
    HouseSpec,
    MaterialZone,
    SideFacade,
    ZoneRole,
)

Move = tuple[float, float]  # прежняя отметка края → новая


class House(NamedTuple):
    """Общее для всех стен дома."""

    spec: HouseSpec
    plinth: str | None  # материал цоколя; None — цоколя у дома нет
    cfg: Checks


def levels(sheet: FacadeSheet, cfg: Checks) -> FacadeSheet:
    house = House(sheet.spec, _plinth_material(sheet, cfg), cfg)
    return sheet.model_copy(update={"facades": [_wall(f, house) for f in sheet.facades]})


def _wall(f: SideFacade, house: House) -> SideFacade:
    leveled = _cornice(_doors(f, house), house)
    return _zones(leveled, _moves(f, leveled, house.spec), house)


def _ys(z: MaterialZone) -> list[float]:
    return [y for _, y in z.shape]


def _low(z: MaterialZone, spec: HouseSpec, cfg: Checks) -> bool:
    """Цоколь модели — зона роли «цоколь», которая не доходит до карниза."""
    return z.role is ZoneRole.PLINTH and max(_ys(z)) < spec.eaves_m - cfg.eps_m


def _plinth_material(sheet: FacadeSheet, cfg: Checks) -> str | None:
    """Материал цоколя дома — самый частый у цоколя модели; цоколя у дома нет — None."""
    if sheet.spec.plinth_m <= EPS:
        return None
    found = Counter(z.material for f in sheet.facades for z in f.zones if _low(z, sheet.spec, cfg))
    return found.most_common(1)[0][0] if found else None


def _floor_y(d: Element, spec: HouseSpec) -> float:
    return spec.floor_levels()[min(d.floor or 1, spec.floors) - 1]


def _doors(f: SideFacade, house: House) -> SideFacade:
    """Двери — на пол своего этажа, их дети — за ними. Проём, записанный ребёнком другого проёма
    (брак разбора ответа), за ним не едет."""
    moved = {d.id: _door(d, f, house) for d in f.elements if d.cls is ElementClass.DOOR
             and abs(d.y_m - _floor_y(d, house.spec)) > house.cfg.eps_m}
    if not moved:
        return f
    out = [moved.get(e.id) or (e if e.cls in OPENINGS else _child(e, moved, f.elements))
           for e in f.elements]
    out = [e for e in out if e is not None]
    return f.model_copy(update={"elements": [e for e in out if not _blocked(e, moved, out)]})


def _door(d: Element, f: SideFacade, house: House) -> Element:
    """Дверь на полу этажа той же высоты; вместе с козырьком над ней — не выше пола следующего
    этажа и низа карниза стены, если он на ней есть."""
    spec, top = house.spec, d.y_m + d.h_m
    y, ceiling = _floor_y(d, spec), spec.floor_levels()[min(d.floor or 1, spec.floors)]
    if _cornices(f):
        ceiling = min(ceiling, spec.eaves_m - _cornice_h(f))
    over = max((c.y_m + c.h_m - top for c in f.elements
                if c.parent == d.id and c.y_m >= top - EPS), default=0.0)
    return d.model_copy(update={"y_m": y, "h_m": min(d.h_m, ceiling - over - y)})


def _child(e: Element, moved: dict[str, Element], before: list[Element]) -> Element | None:
    """Крыльцо — от земли до низа двери (у двери на земле его нет), остальное — за дверью."""
    if e.cls is ElementClass.PORCH and e.parent in moved:
        y = moved[e.parent].y_m
        return e.model_copy(update={"y_m": 0.0, "h_m": y}) if y > EPS else None
    return follow(e, moved, before)


def _blocked(e: Element, moved: dict[str, Element], elements: list[Element]) -> bool:
    """Выводимый элемент сдвинутой двери налез на чужой проём или его выводимый элемент —
    элементу без места его нет, как в derive.py (gf#242)."""
    if e.parent not in moved or e.cls not in TRIM_OF:
        return False
    return any(hits(e, o) for o in elements
               if (o.cls in OPENINGS or o.cls in TRIM_OF) and (o.parent or o.id) != e.parent)


def _cornices(f: SideFacade) -> list[Element]:
    return [e for e in f.elements if e.cls is ElementClass.CORNICE]


def _cornice_h(f: SideFacade) -> float:
    """Высота карниза стены — как у модели; у нескольких кусков — медиана."""
    return median(e.h_m for e in _cornices(f))


def _cornice(f: SideFacade, house: House) -> SideFacade:
    """Карнизы стены — один во всю стену под отметкой карниза высотой модели, но не ниже верха
    проёмов и их выводимых элементов; места нет — карниза нет."""
    found, eaves, eps = _cornices(f), house.spec.eaves_m, house.cfg.eps_m
    if not found:
        return f
    below = [e.y_m + e.h_m for e in f.elements
             if e.cls in OPENINGS or (e.cls in TRIM_OF and e.parent is not None)]
    h = min(_cornice_h(f), eaves - max(below, default=0.0))
    one = found[0].model_copy(update={"x_m": 0.0, "w_m": f.side.length_m, "y_m": eaves - h,
                                      "h_m": h})
    if len(found) == 1 and all(abs(p - q) <= eps for p, q in zip(box(found[0]), box(one),
                                                                  strict=True)):
        return f  # уже на месте — хвосты float не трогают точные числа
    elements = [one if e is found[0] else e for e in f.elements
                if e.cls is not ElementClass.CORNICE or (e is found[0] and h > eps)]
    return f.model_copy(update={"elements": elements})


def _edges(e: Element) -> Move:
    return e.y_m, e.y_m + e.h_m


def _moves(before: SideFacade, after: SideFacade, spec: HouseSpec) -> list[Move]:
    """Куда уехали низ и верх дверей и карнизов стены; карнизы, слитые в один, — к нему. Земля и
    отметка карниза — края самой стены: они не двигаются, даже если на них стоял край двери."""
    now = {e.id: e for e in after.elements}
    out = [(a, b) for d in before.elements if d.cls is ElementClass.DOOR and d.id in now
           for a, b in zip(_edges(d), _edges(now[d.id]), strict=True)]
    out += [(a, b) for c in _cornices(before) for one in _cornices(after)
            for a, b in zip(_edges(c), _edges(one), strict=True)]
    return [(a, b) for a, b in out if abs(a - b) > EPS and EPS < a < spec.eaves_m - EPS]


def _zones(f: SideFacade, moves: list[Move], house: House) -> SideFacade:
    """Цоколь стены — от земли до `plinth_m`; края остальных зон — за краями дверей, карниза и
    цоколя модели."""
    spec, cfg = house.spec, house.cfg
    top = spec.plinth_m if house.plinth is not None else 0.0
    moves = [(max(_ys(z)), top) for z in f.zones if _low(z, spec, cfg)] + moves
    rest = [_lifted(z, moves, top, cfg) for z in f.zones if not _low(z, spec, cfg)]
    base = ([MaterialZone.rect(ZoneRole.PLINTH, house.plinth, (0.0, 0.0, f.side.length_m, top))]
            if house.plinth is not None else [])
    return f.model_copy(update={"zones": base + [z for z in rest if z is not None]})


def _lifted(z: MaterialZone, moves: list[Move], top: float, cfg: Checks) -> MaterialZone | None:
    """Точки зоны на прежнем краю — на новый, ниже верха цоколя — на верх. Зона, сжатая в
    полосу, пропадает. Зоны модели — прямоугольники (`constraints.ZONE_RECT`), так что сдвиг
    точек по высоте не искажает форму."""
    def moved(y: float) -> float:
        y = next((b for a, b in moves if abs(y - a) <= cfg.eps_m), y)
        return max(y, top)

    shape = [(x, moved(y)) for x, y in z.shape]
    if max(y for _, y in shape) - min(y for _, y in shape) <= cfg.eps_m:
        return None
    role = ZoneRole.MAIN if z.role is ZoneRole.PLINTH else z.role  # «цоколь» до карниза
    return z.model_copy(update={"shape": shape, "role": role})
