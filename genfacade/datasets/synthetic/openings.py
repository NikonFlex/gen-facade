"""Проёмы стены — из плана: место и ширина заданы (`fixed`), высоты ставит правило.

Высоты окон — доли высоты этажа (config/synthetic.toml, как WindowSizeType GenPlan).
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
    OpeningKind,
    OpeningVariant,
    Side,
    VariantKind,
)

FROM_PLAN = [FixedField.X, FixedField.W]


def doors(side: Side, spec: HouseSpec, look: Look, rules: FacadeRules) -> list[Element]:
    """Вход — из плана, от пола первого этажа; вид двери — один на дом."""
    found = [o for o in side.openings if o.kind is not OpeningKind.WINDOW]
    variant, height = _door(spec, look, rules)
    return [
        Element(id=f"d{i}", cls=ElementClass.DOOR, x_m=o.x_m, y_m=spec.plinth_m, w_m=o.width_m,
                h_m=height, floor=1, fixed=FROM_PLAN, variant=variant)
        for i, o in enumerate(found, start=1)
    ]


def _door(spec: HouseSpec, look: Look, rules: FacadeRules) -> tuple[OpeningVariant | None, float]:
    """Вид и высота двери. Фрамуга (с козырьком, если он есть) не влезает под карниз —
    дверь со стеклом."""
    door, entry = rules.door, rules.entry
    if look.door is None:
        return None, door.height_m
    tall = door.height_m + door.transom_m
    above = entry.canopy_gap_m + entry.canopy_m if look.canopy else 0.0
    room = spec.floor_heights_m[0] - rules.cornice.height_m
    if look.door is VariantKind.TRANSOM and tall + above <= room + EPS:
        return OpeningVariant(kind=VariantKind.TRANSOM), tall
    cols, rows = door.glazed_panes
    return OpeningVariant(kind=VariantKind.GLAZED, cols=cols, rows=rows), door.height_m


def windows(side: Side, spec: HouseSpec, look: Look, cfg: Windows) -> list[Element]:
    """Окна плана: верх у всех один, низ — по ширине окна (`sill_level`)."""
    base, height = spec.plinth_m, spec.floor_heights_m[0]
    top = min(base + look.window_span[1] * height, base + height - cfg.lintel_m)
    found = [o for o in side.openings if o.kind is OpeningKind.WINDOW]
    out = []
    for i, o in enumerate(found, start=1):
        low = sill_level(o.width_m, look, cfg)
        y = base + low * height
        out.append(Element(
            id=f"w1_{i}", cls=ElementClass.WINDOW, x_m=o.x_m, y_m=round(y, 3), w_m=o.width_m,
            h_m=round(top - y, 3), floor=1, fixed=FROM_PLAN,
            variant=_variant(o.width_m, top - y, low, cfg)))
    return out


def sill_level(width_m: float, look: Look, cfg: Windows) -> float:
    """Низ окна в долях высоты этажа: узкое — высоко, большое — в пол (если так у дома),
    остальные — по уровню дома."""
    if width_m >= cfg.wide_min_w_m - EPS and look.wide_to_floor:
        return 0.0
    if width_m <= cfg.narrow_max_w_m + EPS:
        return max(cfg.narrow_low, look.window_span[0])
    return look.window_span[0]


def _variant(w: float, h: float, low: float, cfg: Windows) -> OpeningVariant:
    kind = VariantKind.PANORAMIC if low <= EPS else VariantKind.REGULAR  # окно в пол
    rows = 2 if h >= cfg.transom_min_h_m else 1
    return OpeningVariant(kind=kind, cols=max(1, math.ceil(w / cfg.sash_max_w_m - EPS)), rows=rows)
