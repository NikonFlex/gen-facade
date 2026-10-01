"""Декор (facade.md, правило 9): подоконники, наличники, карниз; у входа — крыльцо и козырёк.

Материал декора — роль `trim` палитры. Наличник рисуется под окном: в списке элементов
он раньше окна, и окно ложится поверх.
"""

from genfacade.config import FacadeRules
from genfacade.schema import Element, ElementClass, HouseSpec, PaletteRole, VariantKind


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
