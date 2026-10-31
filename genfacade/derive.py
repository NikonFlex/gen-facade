"""Выводимые элементы проёма (`facade: Состав фасада по уровням`, gf#212): подоконник, наличник,
ставни, козырёк.

Модель шага 4 и генератор синтетики решают у проёма только, есть ли элемент, — признак `Trim`;
прямоугольник считает этот модуль по виду элемента у дома (`HouseSpec.trim`, шаг 1) и размерам
вида (config/derive.toml, по своду правил gf#209) — как в FaçAID и CGA: зависимые элементы ставит
код. Выведенный элемент ссылается на свой проём как на родителя: по этой ссылке признаки читаются
обратно (`flags`), так запись токенами и разбор сходятся.
"""

from typing import NamedTuple

from genfacade.config import Derive
from genfacade.schema import (
    EPS,
    OPENINGS,
    Element,
    ElementClass,
    HouseSpec,
    PaletteRole,
    Trim,
)

# Класс выведенного элемента и класс проёма, у которого бывает признак.
DERIVED = {Trim.SILL: ElementClass.SILL, Trim.CASING: ElementClass.MOLDING,
           Trim.SHUTTERS: ElementClass.BLIND, Trim.CANOPY: ElementClass.CANOPY}
OWNER = {Trim.SILL: ElementClass.WINDOW, Trim.CASING: ElementClass.WINDOW,
         Trim.SHUTTERS: ElementClass.WINDOW, Trim.CANOPY: ElementClass.DOOR}
TRIM_OF = {cls: trim for trim, cls in DERIVED.items()}
TAG = {Trim.SILL: "s", Trim.CASING: "m", Trim.SHUTTERS: "b", Trim.CANOPY: "k"}  # приставка имени

Flags = dict[str, set[Trim]]  # имя проёма → его признаки


class Wall(NamedTuple):
    """Что нужно выводу кроме проёмов: параметры дома, длина стены, размеры видов."""

    spec: HouseSpec
    length_m: float
    cfg: Derive


def flags(elements: list[Element]) -> Flags:
    """Признаки проёмов по выведенным элементам: у какого проёма есть ребёнок какого класса."""
    owner = {e.id: e.cls for e in elements}
    out: Flags = {}
    for e in elements:
        trim = TRIM_OF.get(e.cls)
        if trim is not None and e.parent is not None and owner.get(e.parent) is OWNER[trim]:
            out.setdefault(e.parent, set()).add(trim)
    return out


def base(elements: list[Element]) -> list[Element]:
    """Элементы, которые ставит модель: без классов, выводимых кодом."""
    return [e for e in elements if e.cls not in TRIM_OF]


def place(elements: list[Element], marks: Flags, wall: Wall) -> list[Element]:
    """Элементы модели с признаками → они же с выведенными, в порядке отрисовки: наличник под
    окном, подоконник, ставни и козырёк поверх. Признак вида, которого у дома нет, не выводится."""
    def marked(trim: Trim) -> list[Element]:
        return [e for e in elements if e.cls is OWNER[trim] and trim in marks.get(e.id, ())
                and wall.spec.trim.has(trim)]

    casings = [[_casing(w, wall)] for w in marked(Trim.CASING)]
    sills = [[_sill(w, wall)] for w in marked(Trim.SILL)]
    fit = shutter_fits(elements, marks, wall)
    shutters = [_shutters(w, marks, wall) for w in marked(Trim.SHUTTERS) if w.id in fit]
    canopies = [[c] for d in marked(Trim.CANOPY) if (c := _canopy(d, elements, wall)) is not None]
    keep = _apart([*casings, *sills, *shutters, *canopies], elements)
    return [*(e for g in casings for e in g if e.id in keep), *elements,
            *(e for g in [*sills, *shutters, *canopies] for e in g if e.id in keep)]


def _apart(groups: list[list[Element]], elements: list[Element]) -> set[str]:
    """Имена выведенных элементов, которые не налезают на чужие проёмы, карниз и уже оставленные
    элементы чужих проёмов (gf#242: ставни окна на соседнем, козырёк двери на окне — брак);
    группа (пара ставен) остаётся или уходит целиком. Элементу без места его нет, как ставням у
    угла стены."""
    kept = [e for e in elements if e.cls in OPENINGS or e.cls is ElementClass.CORNICE]
    for group in groups:
        if not any(_hits(d, o) for d in group for o in kept if (o.parent or o.id) != d.parent):
            kept += group
    return {e.id for e in kept}


def _hits(a: Element, b: Element) -> bool:
    w = min(a.x_m + a.w_m, b.x_m + b.w_m) - max(a.x_m, b.x_m)
    h = min(a.y_m + a.h_m, b.y_m + b.h_m) - max(a.y_m, b.y_m)
    return w > EPS and h > EPS


def _child(parent: Element, trim: Trim, box: tuple[float, ...], wall: Wall) -> Element:
    """Выведенный элемент: родитель — проём, материал — роль «обрамление», если она есть в
    палитре дома (у реальных домов палитра — одна основная отделка)."""
    x, y, w, h = box
    trim_role = any(m.id == PaletteRole.TRIM for m in wall.spec.materials)
    return Element(id=f"{TAG[trim]}_{parent.id}", cls=DERIVED[trim], x_m=x, y_m=y, w_m=w,
                   h_m=h, floor=parent.floor, parent=parent.id,
                   material=PaletteRole.TRIM if trim_role else None)


def _casing(w: Element, wall: Wall) -> Element:
    c = wall.cfg.casing[wall.spec.trim.casing]
    return _child(w, Trim.CASING, (w.x_m - c, w.y_m, w.w_m + 2 * c, w.h_m + c), wall)


def _sill(w: Element, wall: Wall) -> Element:
    s = wall.cfg.sill[wall.spec.trim.sill]
    return _child(w, Trim.SILL, (w.x_m - s.overhang_m, w.y_m - s.height_m,
                                 w.w_m + 2 * s.overhang_m, s.height_m), wall)


def _offset(w: Element, marks: Flags, wall: Wall) -> float:
    """Ставни — снаружи наличника, если он у окна есть."""
    has = Trim.CASING in marks.get(w.id, ()) and wall.spec.trim.has(Trim.CASING)
    return wall.cfg.casing[wall.spec.trim.casing] if has else 0.0


def _shutter_w(w: Element, wall: Wall) -> float:
    return round(wall.cfg.shutters.share * w.w_m, 3)


def _shutters(w: Element, marks: Flags, wall: Wall) -> list[Element]:
    off, width = _offset(w, marks, wall), _shutter_w(w, wall)
    left = _child(w, Trim.SHUTTERS, (w.x_m - off - width, w.y_m, width, w.h_m), wall)
    right = _child(w, Trim.SHUTTERS, (w.x_m + w.w_m + off, w.y_m, width, w.h_m), wall)
    return [left.model_copy(update={"id": f"{left.id}_l"}),
            right.model_copy(update={"id": f"{right.id}_r"})]


def shutter_fits(elements: list[Element], marks: Flags, wall: Wall) -> set[str]:
    """Окна с признаком ставен, которым хватает места до угла стены или до соседнего проёма
    этажа с его ставнями; остальным ставен нет."""
    out = set()
    for row in _rows(elements):
        needs = [_need(e, marks, wall) for e in row]
        out |= {w.id for i, w in enumerate(row) if needs[i] and _fits(row, needs, i, wall.length_m)}
    return out


def _rows(elements: list[Element]) -> list[list[Element]]:
    """Проёмы стены по этажам, слева направо."""
    floors: dict[int, list[Element]] = {}
    for e in sorted((e for e in elements if e.cls in OPENINGS), key=lambda e: e.x_m):
        floors.setdefault(e.floor or 1, []).append(e)
    return list(floors.values())


def _need(e: Element, marks: Flags, wall: Wall) -> float:
    """Сколько места сбоку займёт ставня проёма; без признака — нисколько."""
    if e.cls is not ElementClass.WINDOW or Trim.SHUTTERS not in marks.get(e.id, ()):
        return 0.0
    return _offset(e, marks, wall) + _shutter_w(e, wall)


def _fits(row: list[Element], needs: list[float], i: int, length_m: float) -> bool:
    w, last = row[i], len(row) - 1
    left = w.x_m - (row[i - 1].x_m + row[i - 1].w_m if i else 0.0)
    right = (row[i + 1].x_m if i < last else length_m) - w.x_m - w.w_m
    return (left + EPS >= needs[i] + (needs[i - 1] if i else 0.0)
            and right + EPS >= needs[i] + (needs[i + 1] if i < last else 0.0))


def _canopy(d: Element, elements: list[Element], wall: Wall) -> Element | None:
    """Козырёк над дверью; под карнизом тесно — ниже, но не ниже min_h_m, иначе его нет."""
    kinds = wall.cfg.canopy
    look = kinds.of(wall.spec.trim.canopy)
    x0, x1 = max(0.0, d.x_m - look.pad_m), min(wall.length_m, d.x_m + d.w_m + look.pad_m)
    y = d.y_m + d.h_m + look.gap_m
    h = min(look.height_m, _ceiling(y, (x0, x1), elements, wall) - y)
    if h + EPS < kinds.min_h_m:
        return None
    return _child(d, Trim.CANOPY, (x0, y, x1 - x0, h), wall)


def _ceiling(y: float, span: tuple[float, float], elements: list[Element], wall: Wall) -> float:
    """Докуда козырёк может подняться: низ карниза над ним или верх стены."""
    above = [c.y_m for c in elements if c.cls is ElementClass.CORNICE and c.y_m + EPS >= y
             and c.x_m < span[1] and c.x_m + c.w_m > span[0]]
    return min([wall.spec.eaves_m, *above])
