import pytest
from pydantic import ValidationError

from genfacade.schema import FacadeSheet, Plan


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


@pytest.fixture
def raw_plan() -> dict:
    """Коробка 6 × 4 м по часовой стрелке: окно на верхней стене, вход на левой."""
    return {
        "walls": [
            {"x0_m": 0, "y0_m": 3.8, "x1_m": 6, "y1_m": 4},
            {"x0_m": 0, "y0_m": 0, "x1_m": 6, "y1_m": 0.2},
            {"x0_m": 0, "y0_m": 0, "x1_m": 0.2, "y1_m": 4},
            {"x0_m": 5.8, "y0_m": 0, "x1_m": 6, "y1_m": 4},
        ],
        "outline": [(0, 0), (0, 4), (6, 4), (6, 0)],
        "openings": [
            {"kind": "window", "rect": {"x0_m": 2, "y0_m": 3.8, "x1_m": 3.5, "y1_m": 4}},
            {"kind": "entrance", "rect": {"x0_m": 0, "y0_m": 1.5, "x1_m": 0.2, "y1_m": 2.4}},
        ],
        "scale_m_per_px": 0.01,
        "source": "manual",
    }


def test_plan_json_roundtrip(raw_plan):
    plan = Plan.model_validate(raw_plan)
    assert Plan.model_validate_json(plan.model_dump_json()) == plan


def test_plan_outline_must_be_clockwise(raw_plan):
    raw_plan["outline"].reverse()
    with pytest.raises(ValidationError, match="по часовой"):
        Plan.model_validate(raw_plan)


def test_plan_outline_needs_three_points(raw_plan):
    raw_plan["outline"] = raw_plan["outline"][:2]
    with pytest.raises(ValidationError, match="не меньше трёх"):
        Plan.model_validate(raw_plan)


def test_empty_rect_rejected(raw_plan):
    raw_plan["walls"][0]["y1_m"] = raw_plan["walls"][0]["y0_m"]
    with pytest.raises(ValidationError, match="пустой прямоугольник"):
        Plan.model_validate(raw_plan)


@pytest.mark.parametrize(("index", "external"), [(1, True), (0, False)])
def test_only_external_non_entrance_can_be_sealed(raw_plan, index, external):
    raw_plan["openings"][index].update(sealed=True, external=external)
    with pytest.raises(ValidationError, match="заделан"):
        Plan.model_validate(raw_plan)


def test_external_window_can_be_sealed(raw_plan):
    raw_plan["openings"][0]["sealed"] = True
    assert Plan.model_validate(raw_plan).openings[0].sealed
