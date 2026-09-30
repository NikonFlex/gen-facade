"""Декор уровня 2 (facade.md, правило 9): подоконники, наличники, карниз.

Материал декора — роль `trim` палитры. Наличник рисуется под окном: в списке элементов
он раньше окна, и окно ложится поверх.
"""

from genfacade.config import LayoutRule
from genfacade.schema import Element, HouseSpec


def sills(windows: list[Element], rule: LayoutRule, trim: str) -> list[Element]:
    """Подоконник у каждого окна, кроме панорамного: у окна в пол подоконной стены нет."""
    s, out = rule.sill, []
    for w in windows:
        if _panoramic(w):
            continue
        out.append(Element(id=f"s_{w.id}", cls="sill", x_m=w.x_m - s.overhang_m,
                           y_m=w.y_m - s.height_m, w_m=w.w_m + 2 * s.overhang_m,
                           h_m=s.height_m, floor=w.floor, parent=w.id, material=trim))
    return out


def casings(windows: list[Element], spec: HouseSpec, rule: LayoutRule, trim: str) -> list[Element]:
    """Наличники — у стилей из config: рамка по бокам и сверху окна."""
    if spec.style not in rule.casing.styles:
        return []
    c = rule.casing.width_m
    return [
        Element(id=f"m_{w.id}", cls="molding", x_m=w.x_m - c, y_m=w.y_m, w_m=w.w_m + 2 * c,
                h_m=w.h_m + c, floor=w.floor, parent=w.id, material=trim)
        for w in windows if not _panoramic(w)
    ]


def cornice(length_m: float, spec: HouseSpec, rule: LayoutRule, trim: str) -> Element:
    """Карниз по всей стене под отметкой карниза из HouseSpec."""
    h = rule.cornice.height_m
    return Element(id="c1", cls="cornice", x_m=0.0, y_m=spec.eaves_m - h, w_m=length_m, h_m=h,
                   material=trim)


def _panoramic(w: Element) -> bool:
    return w.variant is not None and w.variant.kind == "panoramic"
