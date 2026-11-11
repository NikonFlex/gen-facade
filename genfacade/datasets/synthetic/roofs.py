"""Составные крыши синтетики (gf#431, `facade: Крыша над частями дома`, `facade: Щипец над
карнизной стеной`): односкатная крыша пристройки и щипец над входом.

Решения принимаются ПОСЛЕ раскладки стен и со своим потоком случайных чисел: окна, зоны и условие
модели шага 4 от них не зависят (модель стену раскладывает до карниза, крыши частей не видит), а
остальные решения дома по seed не меняются. Жребий каждого решения тянется всегда, чтобы одно не
сдвигало другое.
"""

import random

import shapely

from genfacade import roof
from genfacade.config import Composite, Config
from genfacade.parts import main_wing
from genfacade.schema import (
    EPS,
    FacadeSheet,
    Facing,
    OpeningKind,
    Rect,
    Roof,
    RoofKind,
    WallGable,
)


def compose(rng: random.Random, sheet: FacadeSheet, cfg: Config) -> FacadeSheet:
    """Лист с крышей пристроек и щипцом над входом — там, где они подходят дому."""
    rules = cfg.synthetic.spec.composite
    wing_draw, gable_draw = rng.random(), rng.random()
    if sheet.spec.roof.kind is RoofKind.FLAT:
        return sheet
    if len(sheet.wings) >= 2 and wing_draw < rules.part_p:
        sheet = sheet.model_copy(update={"roofs": part_roofs(rng, sheet, rules)})
    if sheet.spec.roof.kind is RoofKind.GABLE and gable_draw < rules.wall_gable_p:
        sheet = _with_gable(rng, sheet, rules)
    return sheet


def part_roofs(rng: random.Random, sheet: FacadeSheet, rules: Composite) -> list[Roof]:
    """Крыша каждого крыла: у пристройки, что стоит на главном крыле, — односкатная, низ ската
    от главного; у главного и у крыла без общей стороны с ним — крыша дома."""
    house, wings = sheet.spec.roof, sheet.wings
    main = wings[main_wing(wings)]
    own = []
    for w in wings:
        down = _away(main, w)
        pitch = rng.choice(rules.part_pitch_deg)  # жребий — на каждое крыло, как бы ни вышло
        own.append(house if down is None else house.model_copy(update={
            "kind": RoofKind.SHED, "pitch_deg": pitch, "down_to": down}))
    return own


def _away(main: Rect, wing: Rect) -> Facing | None:
    """Сторона плана, в которую от общей стены с главным крылом уходит крыло; нет общей стороны
    (крыло — то же главное или стоит не на нём) — None."""
    shared = shapely.box(main.x0_m, main.y0_m, main.x1_m, main.y1_m).intersection(
        shapely.box(wing.x0_m, wing.y0_m, wing.x1_m, wing.y1_m))
    if not isinstance(shared, shapely.LineString) or shared.length <= EPS:
        return None
    x0, y0, x1, y1 = shared.bounds
    if x1 - x0 <= EPS:  # общая стена — вертикальная, крыло правее или левее неё
        return Facing.X_PLUS if wing.x0_m >= x0 - EPS else Facing.X_MINUS
    return Facing.Y_PLUS if wing.y0_m >= y0 - EPS else Facing.Y_MINUS


def _with_gable(rng: random.Random, sheet: FacadeSheet, rules: Composite) -> FacadeSheet:
    """Лист со щипцом над входом, если он встал: крыша строится на одну часть больше."""
    share, pitch = rng.uniform(*rules.wall_gable_share), rng.choice(rules.wall_gable_pitch_deg)
    house = roof.roofs(sheet)
    found = None if house is None else _over_entrance(sheet, house, share, pitch, rules)
    if found is None:
        return sheet
    out = sheet.model_copy(update={"wall_gables": [found]})
    built = roof.roofs(out)
    return out if built is not None and len(built.parts) == len(house.parts) + 1 else sheet


def _over_entrance(sheet: FacadeSheet, house: roof.HouseRoof, share: float, pitch: float,
                   rules: Composite) -> WallGable | None:
    """Щипец над карнизной стеной со входом: середина — над серединой входа, но целиком внутри
    участка стены своей части с отступом свеса от его краёв; уже `wall_gable_min_m` — None."""
    for k in sorted(roof.eave_walls(sheet)):
        door = next((o for o in sheet.facades[k].side.openings
                     if o.kind is OpeningKind.ENTRANCE), None)
        if door is None:
            continue
        mid = door.x_m + door.width_m / 2
        span = next(s for s in house.spans[k] if s.x0 - EPS <= mid <= s.x1 + EPS)
        if sheet.roofs and sheet.roofs[span.part].kind is not RoofKind.GABLE:
            continue
        gap = house.parts[span.part].overhang
        room = span.x1 - span.x0 - 2 * gap
        width = min(share * (span.x1 - span.x0), room)
        if width < rules.wall_gable_min_m:
            continue
        x0 = min(max(mid - width / 2, span.x0 + gap), span.x1 - gap - width)
        return WallGable(side=k, x0_m=round(x0, 3), x1_m=round(x0 + width, 3), pitch_deg=pitch)
    return None
