"""Крыши частей при генерации (gf#431, `facade: Крыша пристройки при генерации`).

Правило: крыло ниже главного по карнизу, что стоит на нём общей стеной, — пристройка под
односкатной крышей низом ската от главного; остальные крылья — под крышей дома. Выбрано по
разметке настоящих домов против «крыши дома на всех частях» и порога по признаку крыла, выученного
с исключением по дому (`tools/part_roofs_probe.py`, `docs/decisions.md` 11.11.2026).
"""

import shapely

from genfacade.config import Parts
from genfacade.parts import main_wing
from genfacade.schema import EPS, FacadeSheet, Facing, Rect, Roof, RoofKind


def chosen(sheet: FacadeSheet, rule: Parts) -> FacadeSheet:
    """Лист с крышами частей по правилу; правило выключено, крыша плоская, крыльев меньше двух
    или пристроек нет — лист как есть (у всех частей крыша дома)."""
    home = sheet.spec.roof
    if not rule.annex_shed or home.kind is RoofKind.FLAT or len(sheet.wings) < 2:
        return sheet
    own = annex_roofs(sheet, rule.annex_pitch_deg)
    return sheet if all(r is home for r in own) else sheet.model_copy(update={"roofs": own})


def annex_roofs(sheet: FacadeSheet, pitch_deg: float) -> list[Roof]:
    """Крыша каждого крыла листа: у пристройки — односкатная `pitch_deg` низом от главного, у
    остальных — крыша дома (тот же объект `sheet.spec.roof`)."""
    home, wings = sheet.spec.roof, sheet.wings
    main = main_wing(wings)
    eaves = wing_eaves(sheet)
    out = []
    for i, w in enumerate(wings):
        down = away(wings[main], w)
        annex = down is not None and eaves[i] < eaves[main] - EPS
        out.append(home.model_copy(update={"kind": RoofKind.SHED, "pitch_deg": pitch_deg,
                                           "down_to": down}) if annex else home)
    return out


def wing_eaves(sheet: FacadeSheet) -> list[float]:
    """Карниз каждого крыла: по участкам стен, у крыла без участков (дом одной высоты) — дома."""
    found = {r.part: r.eaves_m for f in sheet.facades for r in f.runs}
    return [found.get(i, sheet.spec.eaves_m) for i in range(len(sheet.wings))]


def away(main: Rect, wing: Rect) -> Facing | None:
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
