"""Шаг 5: окна, карниз, цоколь и низ двери — на отметки параметров дома (gf#272, gf#275,
`facade: Высоты цоколя и карниза — из параметров`, `facade: Нуль отметок — земля`).

Параметры дома одни на все стены, а модель шага 4 ставит эти уровни на каждой стене по-своему:
карниз куском посреди стены и ниже отметки карниза, цоколь на одной стене из четырёх и выше
отметки цоколя, дверь на 1,85 м при поле 0,76 (листы проверки gf#268). Поэтому их ставит код:
- дверь — низ на полу своего этажа (`floor_levels`), высота та же, но с козырьком не выше
  отметки карниза; козырёк едет с ней (follow.py) и пропадает, если налез на чужой проём, как в
  derive.py; крыльцо — от земли до её низа. Гаражные ворота стоят на земле, их не трогаем;
- крыльцо — у двери первого этажа, чей низ выше земли больше `porch_min_m` (gf#276): площадка от
  земли до низа двери, шире двери на `porch_pad_m`, материал цоколя. Крыльцо модели у двери не
  дублируется, а встаёт на те же отметки; у двери на земле крыльца нет;
- карниз — во всю стену, верх на `eaves_m`, высота — как у карниза модели на этой стене (у
  нескольких кусков — медиана), низ не ниже верха проёмов; стене без карниза он не добавляется —
  у настоящих домов карниз бывает только на части стен; на стене без края ската (щипцовая,
  высокая стена односкатной крыши, `roof.eave_walls`) карниза нет — у настоящих домов теста его
  там нет (gf#320, хозяин 07.11: «карниз выпирает за крышу»);
- цоколь — если он у дома есть (`plinth_m > 0` и модель поставила его хоть на одной стене) — на
  всех стенах от земли до `plinth_m`, материал — самый частый у цоколя модели. У 9 из 27 настоящих
  домов реального теста `plinth_m > 0` (пол поднят), а зоны цоколя нет — её не добавляем, если
  модель её не ставила. Зона «цоколь» модели до самого карниза — основная отделка, а не цоколь;
- окно во фронтоне (этажа под скатом, gf#321) стоит где стоит: у него нет пола и линии этажа;
- окно — низ не ниже пола своего этажа (не в цоколе); верх, отскочивший от общей линии этажа
  дальше `window_jump_m`, — на линию (gf#275). Линия — медиана верха окон этажа на всех стенах
  дома: окна разных стен видны вместе на углу и в 3D, а настоящие дома держат их на одной высоте с
  разбросом в сантиметры. Окно в пол линии не держит; подоконник, наличник, ставни — за окном;
- остальные зоны модели упираются в края окон, дверей, карниза и цоколя (`validate._anchored`):
  эти края едут на новые отметки вместе с ними, а что ниже верха цоколя — поднимается до него.
"""

from collections import Counter
from statistics import median
from typing import NamedTuple

from genfacade import roof
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
    PaletteRole,
    SideFacade,
    VariantKind,
    ZoneRole,
)

Move = tuple[float, float]  # прежняя отметка края → новая


class House(NamedTuple):
    """Общее для всех стен дома."""

    spec: HouseSpec
    plinth: str | None  # материал цоколя; None — цоколя у дома нет
    heads: dict[int, float]  # этаж → общая линия верха окон по дому
    eaves: set[int]  # стены с карнизом — под краем ската
    cfg: Checks


def levels(sheet: FacadeSheet, cfg: Checks) -> FacadeSheet:
    house = House(sheet.spec, _plinth_material(sheet, cfg), _heads(sheet), roof.eave_walls(sheet),
                  cfg)
    return sheet.model_copy(update={"facades": [_wall(k, f, house)
                                                for k, f in enumerate(sheet.facades)]})


def _wall(k: int, f: SideFacade, house: House) -> SideFacade:
    if k not in house.eaves:
        f = f.model_copy(update={"elements": [e for e in f.elements
                                              if e.cls is not ElementClass.CORNICE]})
    leveled = _porches(_cornice(_doors(_windows(f, house), house), house), house)
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


def _floor(e: Element, spec: HouseSpec) -> int:
    return min(e.floor or 1, spec.floors)


def _floor_y(d: Element, spec: HouseSpec) -> float:
    return spec.floor_levels()[_floor(d, spec) - 1]


def _in_floor(w: Element) -> bool:
    """Окно в пол: линии верха этажа не держит, его низ — пол."""
    return w.variant is not None and w.variant.kind is VariantKind.PANORAMIC


def _heads(sheet: FacadeSheet) -> dict[int, float]:
    """Общая линия верха окон этажа — медиана верха окон этажа на всех стенах, кроме окон в пол
    и во фронтоне."""
    tops: dict[int, list[float]] = {}
    for f in sheet.facades:
        for w in f.elements:
            roofed = roof.under_roof(w, sheet.spec.floors)
            if w.cls is ElementClass.WINDOW and not _in_floor(w) and not roofed:
                tops.setdefault(_floor(w, sheet.spec), []).append(w.y_m + w.h_m)
    return {n: median(ys) for n, ys in tops.items()}


def _windows(f: SideFacade, house: House) -> SideFacade:
    """Окна — не ниже пола этажа и на линии верха этажа, их дети — за ними. Окно, которое на новом
    месте налезло бы на другой проём, остаётся где было: брак сдвига хуже неровной линии."""
    moved = {w.id: m for w in f.elements
             if w.cls is ElementClass.WINDOW and not roof.under_roof(w, house.spec.floors)
             and (m := _window(w, house)) is not None
             and not any(hits(m, o) for o in f.elements if o.cls in OPENINGS and o.id != w.id)}
    return _shifted(f, moved)


def _window(w: Element, house: House) -> Element | None:
    """Окно на отметках этажа или None, если оно на них и стоит. Вверх из цоколя оно едет целиком;
    к линии верха — тоже целиком, но не ниже пола, тогда низ остаётся на полу."""
    spec, cfg = house.spec, house.cfg
    floor = _floor_y(w, spec)
    y, h = max(w.y_m, floor), w.h_m
    line = house.heads.get(_floor(w, spec))
    if (line is not None and not _in_floor(w) and abs(y + h - line) > cfg.window_jump_m
            and line - floor > cfg.eps_m):
        y = max(line - h, floor)
        h = line - y
    if abs(y - w.y_m) <= cfg.eps_m and abs(h - w.h_m) <= cfg.eps_m:
        return None
    return w.model_copy(update={"y_m": y, "h_m": h})


def _shifted(f: SideFacade, moved: dict[str, Element]) -> SideFacade:
    """Сдвинутые проёмы на место, их дети — за ними; ребёнок, налезший на чужой проём, пропадает.
    Проём, записанный ребёнком другого проёма (брак разбора ответа), за ним не едет."""
    if not moved:
        return f
    out = [moved.get(e.id) or (e if e.cls in OPENINGS else _child(e, moved, f.elements))
           for e in f.elements]
    out = [e for e in out if e is not None]
    return f.model_copy(update={"elements": [e for e in out if not _blocked(e, moved, out)]})


def _doors(f: SideFacade, house: House) -> SideFacade:
    """Двери — на пол своего этажа, их дети — за ними."""
    moved = {d.id: _door(d, f, house) for d in f.elements if d.cls is ElementClass.DOOR
             and abs(d.y_m - _floor_y(d, house.spec)) > house.cfg.eps_m}
    return _shifted(f, moved)


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
        return _grounded(e, y) if y > EPS else None
    return follow(e, moved, before)


def _grounded(porch: Element, door_y: float) -> Element:
    """Крыльцо от земли до низа двери; стоит так — как было."""
    if abs(porch.y_m) <= EPS and abs(porch.h_m - door_y) <= EPS:
        return porch
    return porch.model_copy(update={"y_m": 0.0, "h_m": door_y})


def _porches(f: SideFacade, house: House) -> SideFacade:
    """Крыльцо у каждой двери первого этажа, чей низ выше земли больше `porch_min_m`: крыльцо
    модели у двери (по x, `parent` у разбора ответа бывает пустым или чужим) встаёт от земли до
    низа двери, а если его нет — ставится новое."""
    raised = [d for d in f.elements if d.cls is ElementClass.DOOR and (d.floor or 1) == 1
              and d.y_m > house.cfg.porch_min_m]
    fixed: dict[str, Element] = {}
    added = []
    for d in raised:
        mine = [p for p in f.elements if p.cls is ElementClass.PORCH and _across(p, d)]
        fixed |= {p.id: _grounded(p, d.y_m) for p in mine}
        if not mine and (new := _porch(d, f.side.length_m, house)) is not None:
            added.append(new)
    if not fixed and not added:
        return f
    return f.model_copy(update={"elements": [fixed.get(e.id, e) for e in f.elements] + added})


def _across(porch: Element, door: Element) -> bool:
    """Крыльцо стоит у двери: они пересекаются по x."""
    return min(porch.x_m + porch.w_m, door.x_m + door.w_m) - max(porch.x_m, door.x_m) > EPS


def _porch(d: Element, length_m: float, house: House) -> Element | None:
    """Новое крыльцо двери: шире двери на запас, но в пределах стены; дверь за краем стены
    (ответ недоученной модели, gf#217) — брак валидатора, крыльца у неё нет."""
    pad = house.cfg.porch_pad_m
    x0, x1 = max(0.0, d.x_m - pad), min(length_m, d.x_m + d.w_m + pad)
    if x1 - x0 <= EPS:
        return None
    return Element(id=f"p_{d.id}", cls=ElementClass.PORCH, x_m=x0, y_m=0.0, w_m=x1 - x0,
                   h_m=d.y_m, floor=1, parent=d.id, material=_porch_material(house))


def _porch_material(house: House) -> str | None:
    """Материал крыльца — цоколь дома: тот, что у зон цоколя, а если зон нет — роль «цоколь»
    палитры, а нет и её — материала нет (цвет по классу)."""
    if house.plinth is not None:
        return house.plinth
    has = any(m.id == PaletteRole.PLINTH for m in house.spec.materials)
    return PaletteRole.PLINTH if has else None


def _blocked(e: Element, moved: dict[str, Element], elements: list[Element]) -> bool:
    """Выводимый элемент сдвинутого проёма налез на чужой проём или его выводимый элемент —
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
             if (e.cls in OPENINGS or (e.cls in TRIM_OF and e.parent is not None))
             and not roof.under_roof(e, house.spec.floors)]  # окно во фронтоне — не под карнизом
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
    """Куда уехали низ и верх окон, дверей и карнизов стены; карнизы, слитые в один, — к нему.
    Земля и отметка карниза — края самой стены: они не двигаются, даже если на них стоял край
    проёма."""
    now = {e.id: e for e in after.elements}
    shifted = (ElementClass.WINDOW, ElementClass.DOOR)
    out = [(a, b) for d in before.elements if d.cls in shifted and d.id in now
           for a, b in zip(_edges(d), _edges(now[d.id]), strict=True)]
    out += [(a, b) for c in _cornices(before) for one in _cornices(after)
            for a, b in zip(_edges(c), _edges(one), strict=True)]
    return [(a, b) for a, b in out if abs(a - b) > EPS and EPS < a < spec.eaves_m - EPS]


def _zones(f: SideFacade, moves: list[Move], house: House) -> SideFacade:
    """Цоколь стены — от земли до `plinth_m`; края остальных зон — за краями окон, дверей,
    карниза и цоколя модели."""
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
