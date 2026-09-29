import json
from pathlib import Path

import pytest

from genfacade import config
from genfacade.schema import FacadeSheet
from genfacade.unfold import unfold

FIXTURES = {p.stem: p for p in sorted((Path(__file__).parent / "fixtures").glob("house_*.json"))}


def _load(name: str) -> FacadeSheet:
    return FacadeSheet.model_validate_json(FIXTURES[name].read_text())


@pytest.fixture(params=sorted(FIXTURES))
def house(request) -> FacadeSheet:
    """Каждый тестовый дом по очереди."""
    return _load(request.param)


@pytest.fixture
def load_house():
    """Тестовый дом по имени: house_gable, house_hip, house_flat."""
    return _load


@pytest.fixture
def raw_house() -> dict:
    """Двускатный дом как словарь — портить поля в тестах схемы."""
    return json.loads(FIXTURES["house_gable"].read_text())


@pytest.fixture(scope="session")
def cfg() -> config.Config:
    """Настройки пакета по умолчанию."""
    return config.load()


@pytest.fixture
def unfold_sheet(cfg):
    """Развёртка с настройками по умолчанию: дом или его имя → дом с силуэтами."""
    def run(sheet: FacadeSheet | str) -> FacadeSheet:
        house = _load(sheet) if isinstance(sheet, str) else sheet
        return unfold(house, cfg.library.roof.thickness_m)

    return run
