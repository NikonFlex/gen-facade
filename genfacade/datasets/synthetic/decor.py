"""Декор (`facade: Состав фасада по уровням`): признаки выводимых элементов у проёмов, карниз,
крыльцо у входа.

Подоконник, наличник, ставни и козырёк правило не рисует, а только отмечает у проёма — как модель
шага 4; прямоугольник ставит код (genfacade/derive.py), один и тот же для эталона и модели (gf#212).
Материал карниза — роль `trim` палитры.
"""

import shapely

from genfacade import derive, roof
from genfacade.derive import Flags
from genfacade.schema import EPS, Element, ElementClass, HouseSpec, PaletteRole, Trim, VariantKind


def flags(windows: list[Element], doors: list[Element], wall: derive.Wall,
          shape: shapely.Geometry | None = None) -> Flags:
    """Признаки по правилу: подоконник и наличник — у окна не в пол (у окна в пол подоконной
    стены нет), ставни — у такого окна, если им хватает места, козырёк — над входом.

    Окно во фронтоне (этажа под скатом, gf#321) — те же признаки, что у окна этажа (у настоящих
    домов со ставнями они есть у каждого окна выше карниза, gf#373), но ставни — только если пара
    целиком в силуэте стены с фронтоном `shape`: за скат они не выходят (валидатор: `outside`).
    У окна по скату (gf#319) рамка выходит за скат, и ставни по этой же проверке не встают."""
    has = wall.spec.trim.has
    out: Flags = {}
    for w in windows:
        if not _panoramic(w):
            out[w.id] = {t for t in (Trim.SILL, Trim.CASING, Trim.SHUTTERS) if has(t)}
        if (roof.under_roof(w, wall.spec.floors) and Trim.SHUTTERS in out.get(w.id, ())
                and not _in_shape(w, out, wall, shape)):
            out.get(w.id, set()).discard(Trim.SHUTTERS)
    for d in doors:
        out[d.id] = {Trim.CANOPY} if has(Trim.CANOPY) else set()
    fit = derive.shutter_fits([*windows, *doors], out, wall)
    for w in windows:
        if w.id not in fit:
            out.get(w.id, set()).discard(Trim.SHUTTERS)
    return out


def _in_shape(w: Element, out: Flags, wall: derive.Wall, shape: shapely.Geometry | None) -> bool:
    """Пара ставен окна во фронтоне лежит в силуэте стены с фронтоном; силуэта нет — не лежит."""
    if shape is None:
        return False
    grown = shape.buffer(EPS, join_style="mitre")
    return all(grown.contains(shapely.box(s.x_m, s.y_m, s.x_m + s.w_m, s.y_m + s.h_m))
               for s in derive.shutters_of(w, out, wall))


def porch(door: Element, spec: HouseSpec, pad_m: float) -> Element:
    """Крыльцо — площадка перед дверью на высоту цоколя, шире двери на запас шага 5
    (`Checks.porch_pad_m`): такое же ставит код, когда модель крыльца не поставила."""
    return Element(id=f"p_{door.id}", cls=ElementClass.PORCH, x_m=door.x_m - pad_m, y_m=0.0,
                   w_m=door.w_m + 2 * pad_m, h_m=spec.plinth_m, floor=1, parent=door.id,
                   material=PaletteRole.PLINTH)


def cornice(length_m: float, spec: HouseSpec, height_m: float) -> Element:
    """Карниз по всей стене под отметкой карниза из HouseSpec; высота — одна на дом."""
    return Element(id="c1", cls=ElementClass.CORNICE, x_m=0.0,
                   y_m=round(spec.eaves_m - height_m, 3), w_m=length_m, h_m=height_m,
                   material=PaletteRole.TRIM)


def _panoramic(w: Element) -> bool:
    return w.variant is not None and w.variant.kind is VariantKind.PANORAMIC
