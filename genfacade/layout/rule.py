"""Шаг 4 до модели: раскладка стены правилом (generation.md, п. 3–4; facade.md, правило 9).

Интерфейс — как будет у модели: стена после развёртки + контекст → стена с элементами и
зонами. Модель встанет на место `place`, остальной конвейер не меняется (docs/dev-plan.md).
"""

from dataclasses import dataclass

from genfacade.config import LayoutRule
from genfacade.layout import decor, openings
from genfacade.layout.zones import palette_roles, zones
from genfacade.schema import FacadeSheet, HouseSpec, Mode, SideFacade


@dataclass(frozen=True)
class LayoutContext:
    """Условие раскладки: общее для всех стен дома."""

    spec: HouseSpec
    mode: Mode
    text: str  # для модели шага 4 (generation.md, п. 3); правило текст не читает


def place(wall: SideFacade, ctx: LayoutContext, rule: LayoutRule) -> SideFacade:
    spec, trim = ctx.spec, palette_roles(ctx.spec)["trim"]
    doors = openings.doors(wall.side, spec, rule)
    cols = openings.columns(wall.side, ctx.mode, rule.blind)
    windows = openings.windows(cols, spec, rule.windows.level, rule.windows)
    # порядок — порядок отрисовки: наличник под окном, подоконник и карниз поверх стены
    elements = [
        *decor.casings(windows, spec, rule, trim), *windows, *doors,
        *decor.sills(windows, rule, trim), decor.cornice(wall.side.length_m, spec, rule, trim),
    ]
    return wall.model_copy(update={"elements": elements,
                                   "zones": zones(wall, spec, doors, rule)})


def place_all(sheet: FacadeSheet, ctx: LayoutContext, rule: LayoutRule) -> FacadeSheet:
    """Все стены дома при одном контексте (generation.md, п. 8)."""
    return sheet.model_copy(update={"facades": [place(f, ctx, rule) for f in sheet.facades]})
