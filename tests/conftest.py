"""Общие фикстуры: всё — на одном простом доме (tests/simple_house.py, gf#58).

Дом и фасады — стабы моделей (genfacade/models/): один этаж, плоская крыша (других крыш
пока нет — хозяин 01.10).
"""

import json

import pytest
from simple_house import SIMPLE

from genfacade import config
from genfacade.models import stub
from genfacade.pipeline import walls
from genfacade.plan.preprocess import preprocess
from genfacade.schema import Description, FacadeSheet, Mode, Sample, Source, Split, TextKind


@pytest.fixture(scope="session")
def cfg() -> config.Config:
    """Настройки пакета по умолчанию."""
    return config.load()


@pytest.fixture
def preprocess_svg(cfg):
    """Препроцессор с настройками по умолчанию: текст SVG или путь → Plan."""
    def run(svg=SIMPLE, mode=Mode.WITH_OPENINGS):
        return preprocess(svg, mode, cfg.plan)

    return run


@pytest.fixture
def simple_svg():
    """Текст простого плана с заменами: (было, стало), … — испортить план для теста отказа."""
    def edit(*replacements: tuple[str, str]) -> str:
        text = SIMPLE.read_text()
        for old, new in replacements:
            assert old in text, old
            text = text.replace(old, new)
        return text

    return edit


@pytest.fixture
def lay_out(cfg):
    """Простой дом после шагов 1–4: стаб шага 1 → план → стены с силуэтами → стаб шага 4.

    svg — план вместо простого.
    """
    def run(mode: Mode = Mode.WITH_OPENINGS, svg=SIMPLE) -> FacadeSheet:
        plan = preprocess(svg, mode, cfg.plan)
        house = stub.spec_model("")
        return stub.layout_all(walls(house, plan), stub.LayoutContext(house, mode, ""))

    return run


@pytest.fixture
def house(lay_out) -> FacadeSheet:
    """Простой дом после шагов 1–4 — как его рисует лист (шаг 6)."""
    return lay_out()


@pytest.fixture
def sample(house, preprocess_svg) -> Sample:
    """Простой дом как пример датасета: план, эталонные фасады, одно описание."""
    text = Description(kind=TextKind.MANUAL, text="A simple one-storey house with a flat roof.")
    return Sample(id="simple_house", source=Source.SYNTHETIC, split=Split.TRAIN,
                  plan=preprocess_svg(), sheet=house, texts=[text])


@pytest.fixture
def raw_house(lay_out) -> dict:
    """Простой дом как словарь — портить поля в тестах схемы."""
    return json.loads(lay_out().model_dump_json())
