"""Правило шага 1: описание на английском → HouseSpec (generation.md, п. 2; gf#51)."""

import json
from pathlib import Path

import pytest

from genfacade.spec.rule import from_text

TEXTS_EN = Path(__file__).parents[1] / "fixtures" / "texts" / "en.json"
TEXTS = json.loads(TEXTS_EN.read_text())["cases"]


@pytest.mark.parametrize("case", TEXTS, ids=[c["text"][:40] for c in TEXTS])
def test_floors_roof_and_type_from_text(cfg, case):
    spec, found = from_text(case["text"], cfg.spec)
    assert spec.building_type == case["building_type"]
    for field, got in (("floors", spec.floors), ("roof", spec.roof.kind)):
        if case[field] is None:
            assert found[field] is None, f"{field}: в тексте нет, а нашлось {found[field]!r}"
        else:
            assert got == case[field] and found[field]


def test_defaults_when_text_says_nothing(cfg):
    spec, found = from_text("A house.", cfg.spec)
    d = cfg.spec.defaults
    assert (spec.building_type, spec.floors, spec.style) == ("cottage", d.cottage_floors, d.style)
    assert spec.roof.kind == cfg.spec.styles[d.style].roof
    assert all(v is None for v in found.values())


def test_apartment_defaults_to_flat_roof_and_more_floors(cfg):
    spec, _ = from_text("An apartment building.", cfg.spec)
    assert spec.floors == cfg.spec.defaults.apartment_floors
    assert spec.roof.kind == cfg.spec.defaults.apartment_roof


def test_heights_add_up(cfg):
    spec, _ = from_text("Two-storey house with tall ceilings.", cfg.spec)
    high = cfg.spec.floor_height_m["high"]
    assert spec.floor_heights_m == [high, high]
    assert spec.eaves_m == pytest.approx(spec.plinth_m + 2 * high)


def test_palette_by_roles_and_named_material(cfg):
    spec, found = from_text("Brick cottage with a stone plinth.", cfg.spec)
    kinds = {m.id: m.kind for m in spec.materials}
    assert kinds["main"] == "brick" and kinds["plinth"] == "stone"
    assert set(kinds) == set(cfg.spec.styles[spec.style].palette)
    assert spec.roof.material == "roof" and found["material.main"] == "Brick"


@pytest.mark.parametrize("text", ["A hipster loft.", "A catalog house.", "Stories of a house."])
def test_whole_words_only(cfg, text):
    _, found = from_text(text, cfg.spec)
    assert found["roof"] is None and found["material.main"] is None and found["floors"] is None
