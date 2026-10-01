"""Общие фикстуры: всё — на одном простом доме (tests/fixtures/simple_house.svg, gf#58).

План 10 × 5 м в формате GenPlan: вход 0.9 м и окна 1.2 м снизу, 1.0 м слева, 2.0 м сверху,
1.5 м справа; дом и фасады — стабы моделей (genfacade/models/): один этаж, плоская крыша
(других крыш пока нет — хозяин 01.10).
"""

import json
from pathlib import Path

import pytest

from genfacade import config
from genfacade.models import stub
from genfacade.pipeline import walls
from genfacade.plan.preprocess import preprocess
from genfacade.schema import FacadeSheet

SIMPLE = Path(__file__).parent / "fixtures" / "simple_house.svg"


@pytest.fixture(scope="session")
def cfg() -> config.Config:
    """Настройки пакета по умолчанию."""
    return config.load()


@pytest.fixture
def preprocess_svg(cfg):
    """Препроцессор с настройками по умолчанию: текст SVG или путь → Plan."""
    def run(svg=SIMPLE, mode="with_openings"):
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
    def run(mode: str = "with_openings", svg=SIMPLE) -> FacadeSheet:
        plan = preprocess(svg, mode, cfg.plan)
        house = stub.spec_model("")
        return stub.layout_all(walls(house, plan), stub.LayoutContext(house, mode, ""))

    return run


@pytest.fixture
def house(lay_out) -> FacadeSheet:
    """Простой дом после шагов 1–4 — как его рисует лист (шаг 6)."""
    return lay_out()


@pytest.fixture
def raw_house(lay_out) -> dict:
    """Простой дом как словарь — портить поля в тестах схемы."""
    return json.loads(lay_out().model_dump_json())
