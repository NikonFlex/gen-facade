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
    Dormer,
    Element,
    FacadeSheet,
    HouseSpec,
    MaterialZone,
    Mode,
    Refusal,
    Refused,
    Roof,
    RoofKind,
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
    палитра и виды выводимых элементов — отделка дома по тексту (models/finish.py); вид крыши —
    по слову, без слова — отделки, уклон и свес — по виду (gf#320); высота этажа и
    цоколь — заготовки, карниз — над последним этажом."""
    base = json.loads(DATA.joinpath("house.json").read_text())
    wing_phrases = [w for ws in cfg.wing_words.values() for w in ws]
    floors = words.first(words.without(text, wing_phrases, cfg.stem_tail),
                         cfg.floors_words, cfg.stem_tail) or base["floors"]
    wing_floors = words.first(text, cfg.wing_words, cfg.stem_tail)
    style = words.first(text, cfg.style_words, cfg.stem_tail) or base["style"]
    height = base["floor_heights_m"][0]
    house = finish.look(text, style, cfg)
    kind = words.first(text, cfg.roof_words, cfg.stem_tail) or house.roof
    roof = cfg.roof_shape.roof(kind, base["roof"]["material"])
    chimneys, gutters = _roof_items(text, roof.kind is not RoofKind.FLAT, cfg)
    return HouseSpec.model_validate(base | {"roof": roof.model_dump(),
        "chimneys": chimneys, "gutters": gutters,
        "wing_floors": wing_floors, "gable_over_entrance": gable_over_entrance(text, cfg),
        "floors": floors, "floor_heights_m": [height] * floors,
        "style": style, "skylights": _skylights(text, roof, cfg),
        "dormers": _dormers(text, cfg, kind),
        "eaves_m": round(base["plinth_m"] + height * floors, 3),
        "trim": house.trim.model_dump(), "materials": [m.model_dump() for m in house.materials]})


def gable_over_entrance(text: str, cfg: SpecStub) -> bool:
    """Названо ли в тексте щипец над входом (gf#455)."""
    return words.first(text, {True: cfg.entrance_gable_words}, cfg.stem_tail) is True


def _roof_items(text: str, sloped: bool, cfg: SpecStub) -> tuple[list[float], bool]:
    """Труба и водосток дома (gf#454): труба — если названа и перед словом нет «без», в месте по
    настройке; водосток — по настройке, «без водостока» его убирает. У плоской крыши ни того, ни
    другого."""
    found = words.tokens(text)
    chimney, gutters = False, cfg.gutters_default
    for i, token in enumerate(found):
        before = found[i - 1] if i else ""
        no = before in cfg.negations
        if words.named(token, cfg.gutter_words, cfg.stem_tail):
            gutters = not no
        elif words.named(token, cfg.chimney_words, cfg.stem_tail) and not no and not (
                words.named(before, cfg.gutter_words, cfg.stem_tail)):
            chimney = True
    return ([cfg.chimney_at] if chimney and sloped else []), gutters and sloped


def _skylights(text: str, roof: Roof, cfg: SpecStub) -> int:
    """Мансардные окна на скат: текст называет их, перед словом нет отрицания, крыша скатная."""
    found = words.tokens(text)
    named = [i for i in range(len(found))
             if words.phrase_at(found, i, cfg.skylights.words, cfg.stem_tail)
             and not (i and found[i - 1] in cfg.negations)]
    return cfg.skylights.default if named and roof.kind is not RoofKind.FLAT else 0


def _dormers(text: str, cfg: SpecStub, kind: RoofKind) -> list[Dormer]:
    """Слуховые окна по слову текста (gf#457): скатному дому — по дормеру на середине каждого
    карнизного ската; плана у шага 1 нет, скаты — по умолчанию из настроек (`dormers.on_eaves`
    ставит их по плану). «Без дормеров» — дормеров нет."""
    found, tail = words.tokens(text), cfg.stem_tail
    asked = any(words.phrase_at(found, i, cfg.dormer.words, tail)
                and not (i and found[i - 1] in cfg.negations) for i in range(len(found)))
    if not asked or kind is RoofKind.FLAT:
        return []
    return [Dormer(facing=f, at=0.5, width_m=cfg.dormer.width_m, roof=cfg.dormer.roof)
            for f in cfg.dormer.facings]


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
