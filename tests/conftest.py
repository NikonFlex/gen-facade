"""Общие фикстуры: всё — на одном простом доме (tests/simple_house.py, gf#58).

Дом и фасады — стабы моделей (genfacade/models/): один этаж, плоская крыша (других крыш
пока нет — хозяин 01.10).
"""

import json
from importlib.util import find_spec

import pytest
from simple_house import SIMPLE

from genfacade import config, pipeline
from genfacade.datasets.synthetic import batch
from genfacade.metrics import visual
from genfacade.models import stub
from genfacade.pipeline import walls
from genfacade.plan.preprocess import preprocess
from genfacade.schema import Description, FacadeSheet, Mode, Sample, Source, Split, TextKind

# Обучение и модель — в группе [train] с torch; CI её не ставит, и там эти тесты не собираются.
collect_ignore = [] if find_spec("torch") else [
    "unit/test_fit.py", "unit/test_sampling.py", "unit/test_evaluate.py"]
# FID и KID — в группе [visual] с torch-fidelity; CI её не ставит.
collect_ignore += [] if find_spec("torch_fidelity") else ["unit/test_visual.py"]


@pytest.fixture(autouse=True)
def no_inception(monkeypatch):
    """FID и KID в таблице — None: Inception на CPU — секунды на растр, а torch есть не везде.
    Прибор FID/KID проверяет tests/unit/test_visual.py, вызывая его напрямую."""
    monkeypatch.setattr(visual, "available", lambda: False)


@pytest.fixture(scope="module")
def half_val(tmp_path_factory):
    """Сборка синтетических домов в своём конфиге, половина — в val: houses → конфиг."""
    def build(houses: int) -> config.Config:
        root = tmp_path_factory.mktemp("synthetic")
        folder = root / "cfg"
        folder.mkdir()
        (folder / "data.toml").write_text(f'[paths]\nsamples_dir = "{root / "data"}"\n')
        (folder / "synthetic.toml").write_text("[build]\nval_share = 0.5\n")
        cfg = config.load(folder)
        batch.run(range(houses), cfg)
        return cfg
    return build


@pytest.fixture(autouse=True)
def stub_layout(monkeypatch):
    """Конвейер — на стабе шага 4, даже если в data/models лежит обученная модель: тесты не
    зависят от файлов на диске. Тест модели подменяет `pipeline.trained_model` сам."""
    monkeypatch.setattr(pipeline, "trained_model", lambda settings: None)


@pytest.fixture(scope="session")
def cfg() -> config.Config:
    """Настройки пакета по умолчанию."""
    return config.load()


@pytest.fixture
def at(tmp_path):
    """Настройки с корнем данных в tmp_path/<имя>; extra — свои строки synthetic.toml,
    train — свои строки train.toml."""
    def load(name: str, extra: str = "", train: str = "") -> config.Config:
        folder = tmp_path / f"cfg-{name}-{len(extra)}-{len(train)}"
        folder.mkdir()
        (folder / "data.toml").write_text(f'[paths]\nsamples_dir = "{tmp_path / name}"\n')
        (folder / "synthetic.toml").write_text(extra)
        (folder / "train.toml").write_text(train)
        return config.load(folder)

    return load


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
