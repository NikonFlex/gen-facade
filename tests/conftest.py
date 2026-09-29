import json
from pathlib import Path

import pytest

from genfacade.schema import FacadeSheet

FIXTURES = {p.stem: p for p in sorted((Path(__file__).parent / "fixtures").glob("house_*.json"))}


@pytest.fixture(params=sorted(FIXTURES))
def house(request) -> FacadeSheet:
    """Каждый тестовый дом по очереди."""
    return FacadeSheet.model_validate_json(FIXTURES[request.param].read_text())


@pytest.fixture
def load_house():
    """Тестовый дом по имени: house_gable, house_hip, house_flat."""
    return lambda name: FacadeSheet.model_validate_json(FIXTURES[name].read_text())


@pytest.fixture
def raw_house() -> dict:
    """Двускатный дом как словарь — портить поля в тестах схемы."""
    return json.loads(FIXTURES["house_gable"].read_text())


@pytest.fixture(scope="session")
def cfg():
    """Настройки пакета по умолчанию."""
    from genfacade import config

    return config.load()
