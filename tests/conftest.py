"""Общие фикстуры: всё — на одном простом доме (tests/fixtures/simple_house.svg, gf#58).

План 10 × 5 м в формате GenPlan: вход 0.9 м и окна 1.2 м снизу, 1.0 м слева, 2.0 м сверху,
1.5 м справа; дом и фасады — стабы моделей (genfacade/models/): один этаж, плоская крыша.
Для кода, который умеет и другие крыши (развёртка, лист), тот же дом берётся с двускатной
и вальмовой крышей.
"""

import json
from pathlib import Path

import pytest

from genfacade import config
from genfacade.models import stub
from genfacade.pipeline import ridge_along_longest, walls
from genfacade.plan.preprocess import preprocess
from genfacade.schema import FacadeSheet, Roof
from genfacade.unfold import add_roof

SIMPLE = Path(__file__).parent / "fixtures" / "simple_house.svg"
ROOFS = {
    "flat": None,  # как у стаба шага 1 (genfacade/models/stub_data/house.json)
    "gable": Roof(kind="gable", pitch_deg=30, overhang_m=0.5, material="roof"),
    "hip": Roof(kind="hip", pitch_deg=30, overhang_m=0.5, material="roof"),
}


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

    roof — крыша вместо плоской у стаба; svg — план вместо простого.
    """
    def run(mode: str = "with_openings", roof: str = "flat", svg=SIMPLE) -> FacadeSheet:
        plan = preprocess(svg, mode, cfg.plan)
        house = stub.spec_model("")
        house = ridge_along_longest(house.model_copy(update={"roof": ROOFS[roof] or house.roof}),
                                    plan.sides)
        return stub.layout_all(walls(house, plan), stub.LayoutContext(house, mode, ""))

    return run


@pytest.fixture(params=sorted(ROOFS))
def house(request, lay_out, roofed) -> FacadeSheet:
    """Простой дом с каждой крышей по очереди, как на листе (шаг 6): с фронтоном и крышей."""
    return roofed(lay_out(roof=request.param))


@pytest.fixture
def raw_house(lay_out) -> dict:
    """Простой дом как словарь — портить поля в тестах схемы."""
    return json.loads(lay_out().model_dump_json())


@pytest.fixture
def roofed(cfg):
    """Шаг 6: фронтон и крыша по HouseSpec — и пересчёт после правки HouseSpec в тесте."""
    def run(sheet: FacadeSheet) -> FacadeSheet:
        return add_roof(sheet, cfg.library.roof.thickness_m)

    return run
