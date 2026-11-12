"""Щипец над карнизной стеной со входом (gf#455, `facade: Щипец над карнизной стеной`): где он
встаёт — одна функция и у синтетики (`datasets/synthetic/roofs.py`), и у генерации по слову текста
(`pipeline.walls`, `HouseSpec.gable_over_entrance`)."""

from genfacade import roof
from genfacade.config import Parts
from genfacade.schema import (
    EPS,
    FacadeSheet,
    OpeningKind,
    RoofKind,
    WallGable,
)


def chosen(sheet: FacadeSheet, rule: Parts) -> FacadeSheet:
    """Лист со щипцом над входом, если текст его назвал (`spec.gable_over_entrance`) и крыша дома
    двускатная; ширина и уклон — из правила генерации. Не названо или не встал — лист как есть."""
    spec = sheet.spec
    if not spec.gable_over_entrance or spec.roof.kind is not RoofKind.GABLE:
        return sheet
    return placed(sheet, rule.entrance_gable_share, rule.entrance_gable_pitch_deg,
                  rule.entrance_gable_min_m)


def placed(sheet: FacadeSheet, share: float, pitch_deg: float, min_m: float) -> FacadeSheet:
    """Лист со щипцом над входом шириной `share` участка стены и уклоном `pitch_deg`, если он
    встал: крыша строится на одну часть больше; иначе лист как есть."""
    house = roof.roofs(sheet)
    found = None if house is None else over_entrance(sheet, house, share, pitch_deg, min_m)
    if found is None:
        return sheet
    out = sheet.model_copy(update={"wall_gables": [found]})
    built = roof.roofs(out)
    return out if built is not None and len(built.parts) == len(house.parts) + 1 else sheet


def over_entrance(sheet: FacadeSheet, house: roof.HouseRoof, share: float, pitch_deg: float,
                  min_m: float) -> WallGable | None:
    """Щипец над карнизной стеной со входом: середина — над серединой входа, но целиком внутри
    участка стены своей части с отступом свеса от его краёв; уже `min_m` — None."""
    for k in sorted(roof.eave_walls(sheet)):
        door = next((o for o in sheet.facades[k].side.openings
                     if o.kind is OpeningKind.ENTRANCE), None)
        if door is None:
            continue
        mid = door.x_m + door.width_m / 2
        span = next(s for s in house.spans[k] if s.x0 - EPS <= mid <= s.x1 + EPS)
        if sheet.roofs and sheet.roofs[span.part].kind is not RoofKind.GABLE:
            continue
        gap = house.parts[span.part].reach
        room = span.x1 - span.x0 - 2 * gap
        width = min(share * (span.x1 - span.x0), room)
        if width < min_m:
            continue
        x0 = min(max(mid - width / 2, span.x0 + gap), span.x1 - gap - width)
        return WallGable(side=k, x0_m=round(x0, 3), x1_m=round(x0 + width, 3), pitch_deg=pitch_deg)
    return None
