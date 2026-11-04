"""Проёмы стены — из плана: место и ширина заданы (`fixed`), высоты ставит правило.

Высоты — по своду правил фасада (gf#211, config/synthetic.toml): верх окон этажа и двери — одна
линия на дом, высота окна — из рядов.
"""

import math
import random
from collections.abc import Callable
from typing import NamedTuple

from genfacade.config import Config, FacadeRules, Windows
from genfacade.datasets.synthetic import plan
from genfacade.datasets.synthetic.house import Look
from genfacade.schema import (
    DOOR_OPENING_KINDS,
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    FixedField,
    HouseSpec,
    Opening,
    OpeningKind,
    OpeningVariant,
    Side,
    VariantKind,
)
from genfacade.train import constraints, tokens

FROM_PLAN = [FixedField.X, FixedField.W]


class Slot(NamedTuple):
    """Окно по вертикали: низ над землёй, высота и низ над полом этажа (0 — окно в пол)."""

    y_m: float
    h_m: float
    low_m: float


Placer = Callable[[Opening, float], Slot]  # окно ряда и отметка пола его этажа → место по вертикали


def doors(side: Side, spec: HouseSpec, look: Look, rules: FacadeRules) -> list[Element]:
    """Вход — из плана, от пола первого этажа; вид двери — один на дом."""
    found = [o for o in side.openings if o.kind in DOOR_OPENING_KINDS]
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


def windows(rows: list[list[Opening]], spec: HouseSpec, place: Placer, cfg: Windows
            ) -> list[Element]:
    """Окна по этажам (rows — снизу вверх); низ и высоту окна задаёт place — правило линии верха
    (`on_head_line`) или случайная расстановка (`scattered`). Место и ширину задаёт план только на
    первом этаже."""
    out = []
    for floor, (row, base) in enumerate(zip(rows, spec.floor_levels(), strict=False), start=1):
        out += [_window(o, (floor, i), place(o, base), cfg) for i, o in enumerate(row, start=1)]
    return out


def _window(o: Opening, number: tuple[int, int], slot: Slot, cfg: Windows) -> Element:
    """Окно: номер — (этаж, место в ряду). Заданные планом поля — только на первом этаже."""
    floor, i = number
    return Element(
        id=f"w{floor}_{i}", cls=ElementClass.WINDOW, x_m=o.x_m, y_m=slot.y_m, w_m=o.width_m,
        h_m=slot.h_m, floor=floor, fixed=FROM_PLAN if floor == 1 else [],
        variant=_variant(o.width_m, slot.h_m, slot.low_m, cfg))


def on_head_line(look: Look, cfg: Windows) -> Placer:
    """Правила генератора: на этаже верх у всех окон один (look.head_m), низ — по высоте окна
    (`window_height`)."""
    def place(o: Opening, base: float) -> Slot:
        h = window_height(o.width_m, look, cfg)
        top = round(base + look.head_m, 3)  # на миллиметрах: верх окон этажа — один
        return Slot(round(top - h, 3), h, look.head_m - h)

    return place


def scattered(rng: random.Random, sheet: FacadeSheet, look: Look, cfg: Config) -> Placer:
    """Случайная расстановка по вертикали (gf#217): у дома по типоразмеру на ширину окна плана
    (их не больше widths_per_house), высота типоразмера — равномерно от самого низкого окна стража
    до верха окон этажа; окно любого типоразмера — низ равномерно в пределах этажа, целиком внутри
    него: ни линии верха окон, ни привязки к подоконнику."""
    step = cfg.synthetic.spec.grid_m
    lowest = tokens.metres(constraints.norms(cfg).lowest, cfg.tokens)
    # ширины — до миллиметра: окно верхнего этажа берёт ширину с сетки, план читает пикселями
    widths = sorted({round(o.width_m, 3) for f in sheet.facades for o in f.side.openings
                     if o.kind is OpeningKind.WINDOW})
    types = {w: plan.on_grid(rng, (lowest, look.head_m), step) for w in widths}

    def place(o: Opening, base: float) -> Slot:
        h = types[round(o.width_m, 3)]
        low = plan.on_grid(rng, (0.0, look.head_m - h), step)
        return Slot(round(base + low, 3), h, low)

    return place


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
