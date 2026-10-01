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


def doors(side: Side, spec: HouseSpec, rules: FacadeRules) -> list[Element]:
    """Вход — из плана, от пола первого этажа."""
    found = [o for o in side.openings if o.kind is not OpeningKind.WINDOW]
    return [
        Element(id=f"d{i}", cls=ElementClass.DOOR, x_m=o.x_m, y_m=spec.plinth_m, w_m=o.width_m,
                h_m=rules.door.height_m, floor=1, fixed=FROM_PLAN)
        for i, o in enumerate(found, start=1)
    ]


def windows(side: Side, spec: HouseSpec, look: Look, cfg: Windows) -> list[Element]:
    low, high = look.window_span
    base, height = spec.plinth_m, spec.floor_heights_m[0]
    y = base + low * height
    h = min(base + high * height, base + height - cfg.lintel_m) - y
    found = [o for o in side.openings if o.kind is OpeningKind.WINDOW]
    return [
        Element(id=f"w1_{i}", cls=ElementClass.WINDOW, x_m=o.x_m, y_m=round(y, 3),
                w_m=o.width_m, h_m=round(h, 3), floor=1, fixed=FROM_PLAN,
                variant=_variant(o.width_m, h, low, cfg))
        for i, o in enumerate(found, start=1)
    ]


def _variant(w: float, h: float, low: float, cfg: Windows) -> OpeningVariant:
    kind = VariantKind.PANORAMIC if low <= EPS else VariantKind.REGULAR  # окно в пол
    rows = 2 if h >= cfg.transom_min_h_m else 1
    return OpeningVariant(kind=kind, cols=max(1, math.ceil(w / cfg.sash_max_w_m - EPS)), rows=rows)
