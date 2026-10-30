"""Декор (`facade: Состав фасада по уровням`): признаки выводимых элементов у проёмов, карниз,
крыльцо у входа.

Подоконник, наличник, ставни и козырёк правило не рисует, а только отмечает у проёма — как модель
шага 4; прямоугольник ставит код (genfacade/derive.py), один и тот же для эталона и модели (gf#212).
Материал карниза — роль `trim` палитры.
"""

from genfacade import derive
from genfacade.config import FacadeRules
from genfacade.derive import Flags
from genfacade.schema import Element, ElementClass, HouseSpec, PaletteRole, Trim, VariantKind


def flags(windows: list[Element], doors: list[Element], wall: derive.Wall) -> Flags:
    """Признаки по правилу: подоконник и наличник — у окна не в пол (у окна в пол подоконной
    стены нет), ставни — у такого окна, если им хватает места, козырёк — над входом."""
    has = wall.spec.trim.has
    out: Flags = {}
    for w in windows:
        if not _panoramic(w):
            out[w.id] = {t for t in (Trim.SILL, Trim.CASING, Trim.SHUTTERS) if has(t)}
    for d in doors:
        out[d.id] = {Trim.CANOPY} if has(Trim.CANOPY) else set()
    fit = derive.shutter_fits([*windows, *doors], out, wall)
    for w in windows:
        if w.id not in fit:
            out.get(w.id, set()).discard(Trim.SHUTTERS)
    return out


def porch(door: Element, spec: HouseSpec, rules: FacadeRules) -> Element:
    """Крыльцо — площадка перед дверью на высоту цоколя."""
    pad = rules.entry.porch_pad_m
    return Element(id=f"p_{door.id}", cls=ElementClass.PORCH, x_m=door.x_m - pad, y_m=0.0,
                   w_m=door.w_m + 2 * pad, h_m=spec.plinth_m, floor=1, parent=door.id,
                   material=PaletteRole.PLINTH)


def cornice(length_m: float, spec: HouseSpec, height_m: float) -> Element:
    """Карниз по всей стене под отметкой карниза из HouseSpec; высота — одна на дом."""
    return Element(id="c1", cls=ElementClass.CORNICE, x_m=0.0,
                   y_m=round(spec.eaves_m - height_m, 3), w_m=length_m, h_m=height_m,
                   material=PaletteRole.TRIM)


def _panoramic(w: Element) -> bool:
    return w.variant is not None and w.variant.kind is VariantKind.PANORAMIC
