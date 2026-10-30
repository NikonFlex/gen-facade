"""Декор (`facade: Состав фасада по уровням`): подоконники, наличники, ставни, карниз; у входа —
крыльцо и козырёк.

Материал декора — роль `trim` палитры. Наличник рисуется под окном: в списке элементов
он раньше окна, и окно ложится поверх.
"""

from genfacade.config import FacadeRules, Shutter
from genfacade.schema import EPS, Element, ElementClass, HouseSpec, PaletteRole, VariantKind
from genfacade.validate import OPENINGS


def sills(windows: list[Element], rules: FacadeRules) -> list[Element]:
    """Подоконник у каждого окна, кроме панорамного: у окна в пол подоконной стены нет."""
    s = rules.sill
    return [_trim(w, ElementClass.SILL, "s", (w.x_m - s.overhang_m, w.y_m - s.height_m,
                                              w.w_m + 2 * s.overhang_m, s.height_m))
            for w in windows if not _panoramic(w)]


def casings(windows: list[Element], rules: FacadeRules) -> list[Element]:
    """Наличник — рамка по бокам и сверху окна."""
    c = rules.casing.width_m
    return [_trim(w, ElementClass.MOLDING, "m", (w.x_m - c, w.y_m, w.w_m + 2 * c, w.h_m + c))
            for w in windows if not _panoramic(w)]


def shutters(wall: list[Element], length_m: float, offset_m: float,
             rules: Shutter) -> list[Element]:
    """Ставни по бокам окна (не в пол) шириной share его ширины; offset_m — наличник, снаружи
    которого они стоят. Окну, чьи ставни упёрлись бы в угол, соседний проём или его ставни, —
    без ставен."""
    out = []
    for row in _rows(wall):
        needs = [_need(e, offset_m, rules) for e in row]
        for i, w in enumerate(row):
            if needs[i] and _fits(row, needs, i, length_m):
                width = round(rules.share * w.w_m, 3)
                out += [_trim(w, ElementClass.BLIND, "bl", (w.x_m - offset_m - width, w.y_m,
                                                            width, w.h_m)),
                        _trim(w, ElementClass.BLIND, "br", (w.x_m + w.w_m + offset_m, w.y_m,
                                                            width, w.h_m))]
    return out


def _rows(wall: list[Element]) -> list[list[Element]]:
    """Проёмы стены по этажам, слева направо."""
    floors: dict[int, list[Element]] = {}
    for e in sorted((e for e in wall if e.cls in OPENINGS), key=lambda e: e.x_m):
        floors.setdefault(e.floor or 1, []).append(e)
    return list(floors.values())


def _need(e: Element, offset_m: float, rules: Shutter) -> float:
    """Сколько места сбоку займёт ставня проёма; у двери и окна в пол ставен нет."""
    if e.cls is not ElementClass.WINDOW or _panoramic(e):
        return 0.0
    return offset_m + rules.share * e.w_m


def _fits(row: list[Element], needs: list[float], i: int, length_m: float) -> bool:
    """Ставням i-го проёма этажа хватает места до угла или до соседа с его ставнями."""
    w, last = row[i], len(row) - 1
    left = w.x_m - (row[i - 1].x_m + row[i - 1].w_m if i else 0.0)
    right = (row[i + 1].x_m if i < last else length_m) - w.x_m - w.w_m
    return (left + EPS >= needs[i] + (needs[i - 1] if i else 0.0)
            and right + EPS >= needs[i] + (needs[i + 1] if i < last else 0.0))


def porch(door: Element, spec: HouseSpec, rules: FacadeRules) -> Element:
    """Крыльцо — площадка перед дверью на высоту цоколя."""
    pad = rules.entry.porch_pad_m
    return Element(id=f"p_{door.id}", cls=ElementClass.PORCH, x_m=door.x_m - pad, y_m=0.0,
                   w_m=door.w_m + 2 * pad, h_m=spec.plinth_m, floor=1, parent=door.id,
                   material=PaletteRole.PLINTH)


def canopy(door: Element, rules: FacadeRules) -> Element:
    e = rules.entry
    return _trim(door, ElementClass.CANOPY, "k", (
        door.x_m - e.canopy_pad_m, door.y_m + door.h_m + e.canopy_gap_m,
        door.w_m + 2 * e.canopy_pad_m, e.canopy_m))


def _trim(w: Element, cls: ElementClass, tag: str, box: tuple[float, ...]) -> Element:
    """Деталь при окне: ссылается на него как на родителя, материал — отделка палитры."""
    x, y, width, height = box
    return Element(id=f"{tag}_{w.id}", cls=cls, x_m=x, y_m=y, w_m=width, h_m=height,
                   floor=w.floor, parent=w.id, material=PaletteRole.TRIM)


def cornice(length_m: float, spec: HouseSpec, rules: FacadeRules) -> Element:
    """Карниз по всей стене под отметкой карниза из HouseSpec."""
    h = rules.cornice.height_m
    return Element(id="c1", cls=ElementClass.CORNICE, x_m=0.0, y_m=spec.eaves_m - h,
                   w_m=length_m, h_m=h, material=PaletteRole.TRIM)


def _panoramic(w: Element) -> bool:
    return w.variant is not None and w.variant.kind is VariantKind.PANORAMIC
