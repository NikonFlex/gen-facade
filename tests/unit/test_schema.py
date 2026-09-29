import pytest
from pydantic import ValidationError

from genfacade.schema import FacadeSheet


def test_fixtures_load(house):
    assert len(house.facades) == 4


def test_floor_heights_must_match_floors(raw_house):
    raw = raw_house
    raw["spec"]["floors"] = 3
    with pytest.raises(ValidationError, match="floor_heights_m"):
        FacadeSheet.model_validate(raw)


def test_unknown_material_rejected(raw_house):
    raw = raw_house
    raw["facades"][0]["zones"][0]["material"] = "gold"
    with pytest.raises(ValidationError, match="gold"):
        FacadeSheet.model_validate(raw)


def test_unknown_parent_rejected(raw_house):
    raw = raw_house
    sill = next(e for e in raw["facades"][0]["elements"] if e["cls"] == "sill")
    sill["parent"] = "w99"
    with pytest.raises(ValidationError, match="w99"):
        FacadeSheet.model_validate(raw)


def test_typo_in_field_rejected(raw_house):
    raw = raw_house
    raw["facades"][0]["elements"][0]["widht"] = 1.0
    with pytest.raises(ValidationError, match="widht"):
        FacadeSheet.model_validate(raw)


def test_json_roundtrip(house):
    assert FacadeSheet.model_validate_json(house.model_dump_json()) == house
