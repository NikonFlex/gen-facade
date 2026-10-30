"""Проёмы стены — из плана: место и ширина заданы (`fixed`), высоты ставит правило.

Высоты — по своду правил фасада (gf#211, config/synthetic.toml): верх окон этажа и двери — одна
линия на дом, высота окна — из рядов.
"""

import math

from genfacade.config import FacadeRules, Windows
from genfacade.datasets.synthetic.house import Look
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FixedField,
    HouseSpec,
    Opening,
    OpeningKind,
    OpeningVariant,
    Side,
    VariantKind,
)

FROM_PLAN = [FixedField.X, FixedField.W]


def doors(side: Side, spec: HouseSpec, look: Look, rules: FacadeRules) -> list[Element]:
    """Вход — из плана, от пола первого этажа; вид двери — один на дом."""
    found = [o for o in side.openings if o.kind is not OpeningKind.WINDOW]
    variant = _door(look, rules)
    return [
        Element(id=f"d{i}", cls=ElementClass.DOOR, x_m=o.x_m, y_m=spec.plinth_m, w_m=o.width_m,
                h_m=look.head_m, floor=1, fixed=FROM_PLAN, variant=variant)
        for i, o in enumerate(found, start=1)
    ]


def _door(look: Look, rules: FacadeRules) -> OpeningVariant | None:
    """Вид двери. Верх двери — на линии окон (look.head_m); фрамуга над полотном туда не
    влезает — дверь со стеклом."""
    door = rules.door
    if look.door is None:
        return None
    if look.door is VariantKind.TRANSOM and door.height_m + door.transom_m <= look.head_m + EPS:
        return OpeningVariant(kind=VariantKind.TRANSOM)
    cols, rows = door.glazed_panes
    return OpeningVariant(kind=VariantKind.GLAZED, cols=cols, rows=rows)


def windows(rows: list[list[Opening]], spec: HouseSpec, look: Look, cfg: Windows) -> list[Element]:
    """Окна по этажам (rows — снизу вверх): на этаже верх у всех один, низ — по ширине окна
    (`window_height`). Место и ширину задаёт план только на первом этаже."""
    out = []
    for floor, (row, base) in enumerate(zip(rows, spec.floor_levels(), strict=False), start=1):
        out += _row(row, floor, base, look, cfg)
    return out


def _row(row: list[Opening], floor: int, base: float, look: Look, cfg: Windows) -> list[Element]:
    """Окна одного этажа; base — отметка его пола."""
    top = round(base + look.head_m, 3)  # на миллиметрах: верх окон этажа — один
    out = []
    for i, o in enumerate(row, start=1):
        h = window_height(o.width_m, look, cfg)
        out.append(Element(
            id=f"w{floor}_{i}", cls=ElementClass.WINDOW, x_m=o.x_m, y_m=round(top - h, 3),
            w_m=o.width_m, h_m=h, floor=floor, fixed=FROM_PLAN if floor == 1 else [],
            variant=_variant(o.width_m, h, look.head_m - h, cfg)))
    return out


def window_height(width_m: float, look: Look, cfg: Windows) -> float:
    """Высота окна по ширине: большое — в пол (если так у дома), узкое — маленькое, остальные —
    высота дома."""
    if width_m >= cfg.wide_min_w_m - EPS and look.wide_to_floor:
        return look.head_m
    if width_m <= cfg.narrow_max_w_m + EPS:
        return look.narrow_h_m
    return look.window_h_m


def _variant(w: float, h: float, low: float, cfg: Windows) -> OpeningVariant:
    kind = VariantKind.PANORAMIC if low <= EPS else VariantKind.REGULAR  # окно в пол
    rows = 2 if h >= cfg.transom_min_h_m else 1
    return OpeningVariant(kind=kind, cols=max(1, math.ceil(w / cfg.sash_max_w_m - EPS)), rows=rows)
