"""Стабы моделей шагов 1 и 4: интерфейс — как у моделей, ответ — заготовка из stub_data/.

Стаб 1: текст → HouseSpec — заготовка дома, из текста берутся этажность, стиль и отделка:
палитра и виды выводимых элементов (подоконник, наличник, ставни, козырёк, gf#212, gf#303).
Стаб 2: стена после развёртки + контекст → стена с элементами и зонами — готовые фасады
простого дома (tests/fixtures/simple_house.svg), один набор на оба режима; «задано условием»
(fixed) остаётся только у проёмов, которые есть на стороне плана. Заготовку один раз
сделало правило раскладки (gf#50), потом правило удалено (gf#60). Модель встанет на место
функций этого модуля, остальной конвейер не меняется.
"""

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from genfacade.config import SpecStub
from genfacade.models import finish, words
from genfacade.schema import (
    EPS,
    Element,
    FacadeSheet,
    HouseSpec,
    MaterialZone,
    Mode,
    Refusal,
    Refused,
    Side,
    SideFacade,
)

DATA = files(__package__).joinpath("stub_data")


class ModelError(Refused):
    """Модель (стаб) не может ответить на этот вход; code — почему, текст — подробность.
    attempts — попытки обученной модели из трассы (`pipeline.layout`), когда годного ответа
    за них нет (Refusal.MODEL_NO_ANSWER)."""

    def __init__(self, code: Refusal, detail: str, attempts: list[dict] | None = None):
        super().__init__(code, detail)
        self.attempts = attempts or []


@dataclass(frozen=True)
class LayoutContext:
    """Условие раскладки, общее для всех стен дома (`generation: Условие модели шага 4`)."""

    spec: HouseSpec
    mode: Mode
    text: str


def spec_model(text: str, cfg: SpecStub) -> HouseSpec:
    """Шаг 1: описание → параметры дома. Стаб: заготовка, этажей и стиль — по слову в тексте,
    палитра и виды выводимых элементов — отделка дома по тексту (models/finish.py); высота этажа
    и цоколь — заготовки, карниз — над последним этажом."""
    base = json.loads(DATA.joinpath("house.json").read_text())
    floors = words.first(text, cfg.floors_words, cfg.stem_tail) or base["floors"]
    style = words.first(text, cfg.style_words, cfg.stem_tail) or base["style"]
    height = base["floor_heights_m"][0]
    house = finish.look(text, style, cfg)
    return HouseSpec.model_validate(base | {
        "floors": floors, "floor_heights_m": [height] * floors, "style": style,
        "eaves_m": round(base["plinth_m"] + height * floors, 3),
        "trim": house.trim.model_dump(), "materials": [m.model_dump() for m in house.materials]})


def layout_model(wall: SideFacade, ctx: LayoutContext) -> SideFacade:
    """Шаг 4: стена → элементы и зоны. Стаб: заготовка простого дома для этой стороны."""
    side = wall.side
    ready = _facades().get(side.index)
    if ready is None or abs(ready["length_m"] - side.length_m) > EPS:
        raise ModelError(Refusal.HOUSE_OUT_OF_MODEL,
                         f"стаб знает только простой дом 10 × 5 м (simple_house.svg): сторона "
                         f"{side.index} длиной {side.length_m:.2f} м ему не знакома")
    elements = [_planned(Element.model_validate(e), side) for e in ready["elements"]]
    return wall.model_copy(update={
        "elements": elements,
        "zones": [MaterialZone.model_validate(z) for z in ready["zones"]],
    })


def _planned(e: Element, side: Side) -> Element:
    """fixed — только у проёма, который есть на стороне плана: в глухом режиме окна плана
    заделаны, задан один вход (`facade: Проёмы плана — условие`)."""
    on_plan = any(abs(o.x_m - e.x_m) <= EPS and abs(o.width_m - e.w_m) <= EPS
                  for o in side.openings)
    return e if on_plan else e.model_copy(update={"fixed": []})


def layout_all(sheet: FacadeSheet, ctx: LayoutContext) -> FacadeSheet:
    """Все стены дома при одном контексте (`facade: Общие параметры дома`)."""
    if len(sheet.facades) != len(_facades()):
        raise ModelError(Refusal.HOUSE_OUT_OF_MODEL,
                         f"стаб знает только простой дом из {len(_facades())} стен, "
                         f"а у плана их {len(sheet.facades)}")
    return sheet.model_copy(update={"facades": [layout_model(f, ctx) for f in sheet.facades]})


@cache
def _facades() -> dict[int, dict]:
    return {f["side"]: f for f in json.loads(DATA.joinpath("facades.json").read_text())}
