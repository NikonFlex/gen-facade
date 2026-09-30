"""Общие фикстуры: всё — на одном простом доме (tests/fixtures/simple_house.svg, gf#58).

План 10 × 5 м в формате GenPlan: вход 0.9 м и окна 1.2 м снизу, 1.0 м слева, 2.0 м сверху,
1.5 м справа; дом — config/house.json (один этаж, плоская крыша). Для кода, который умеет
и другие крыши (развёртка, лист), тот же дом берётся с двускатной и вальмовой крышей.
"""

import json
from pathlib import Path

import pytest

from genfacade import config
from genfacade.layout.rule import LayoutContext, place_all
from genfacade.pipeline import ridge_along_longest, walls
from genfacade.plan.preprocess import preprocess
from genfacade.schema import FacadeSheet, Roof, SideFacade
from genfacade.unfold import unfold

SIMPLE = Path(__file__).parent / "fixtures" / "simple_house.svg"
ROOFS = {
    "flat": None,  # как в config/house.json
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
    """Простой дом после шагов 2–4: план → стены с силуэтами → раскладка правилом.

    roof — крыша вместо плоской из config/house.json; svg — план вместо простого.
    """
    def run(mode: str = "with_openings", roof: str = "flat", svg=SIMPLE) -> FacadeSheet:
        plan = preprocess(svg, mode, cfg.plan)
        house = cfg.house.model_copy(update={"roof": ROOFS[roof] or cfg.house.roof})
        house = ridge_along_longest(house, plan.sides)
        return place_all(walls(house, plan, cfg), LayoutContext(house, mode, ""), cfg.layout)

    return run


@pytest.fixture(params=sorted(ROOFS))
def house(request, lay_out) -> FacadeSheet:
    """Простой дом с каждой крышей по очереди — для развёртки и листа."""
    return lay_out(roof=request.param)


@pytest.fixture
def raw_house(lay_out) -> dict:
    """Простой дом как словарь — портить поля в тестах схемы."""
    return json.loads(lay_out().model_dump_json())


@pytest.fixture
def unfold_sheet(cfg):
    """Пересчитать силуэты и крышу — после правки HouseSpec в тесте."""
    def run(sheet: FacadeSheet) -> FacadeSheet:
        return unfold(sheet, cfg.library.roof.thickness_m)

    return run


@pytest.fixture
def relayout(cfg):
    """Тот же план, другие параметры дома или раскладки: стороны из sheet, заново шаги 3–4.

    Для того, что правило умеет сверх простого дома (этажи, стиль, уровень окон).
    """
    def run(sheet: FacadeSheet, mode: str = "with_openings", rule=None, **spec) -> FacadeSheet:
        house = sheet.spec.model_copy(update=spec)
        bare = FacadeSheet(spec=house, facades=[SideFacade(side=f.side) for f in sheet.facades])
        bare = unfold(bare, cfg.library.roof.thickness_m)
        return place_all(bare, LayoutContext(house, mode, ""), rule or cfg.layout)

    return run


@pytest.fixture
def two_floors():
    """Параметры двухэтажного варианта простого дома для relayout."""
    return {"floors": 2, "floor_heights_m": [2.75, 2.75], "eaves_m": 6.0}
