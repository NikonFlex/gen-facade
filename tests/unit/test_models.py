"""Стабы моделей шагов 1 и 4 (genfacade/models/stub.py, gf#60)."""

import pytest

from genfacade.models import stub
from genfacade.models.stub import LayoutContext, ModelError
from genfacade.schema import ElementClass, FacadeSheet, Mode, RoofKind


@pytest.mark.parametrize(("text", "floors"), [
    ("A simple one-storey house with a flat roof.", 1),
    ("A Two-Storey villa.", 2),
    ("Двухэтажный коттедж", 2),
    ("A three-story house, not a bungalow", 3),   # слово раньше других
    ("Five-storey apartment block.", 1),          # слова нет — как у заготовки
    ("", 1),
])
def test_spec_stub_reads_only_floors(cfg, text, floors):
    """`generation: Стаб шага 1`: из текста — только этажность; остальное — заготовка: плоская
    крыша, палитра по ролям, высота этажа одна, карниз над последним этажом."""
    spec, base = stub.spec_model(text, cfg.models.spec), stub.spec_model("", cfg.models.spec)
    assert (spec.floors, spec.roof.kind) == (floors, RoofKind.FLAT)
    assert [m.id for m in spec.materials] == ["main", "plinth", "accent", "trim", "roof"]
    assert spec.floor_heights_m == base.floor_heights_m * floors
    assert spec.eaves_m == pytest.approx(spec.plinth_m + floors * base.floor_heights_m[0])
    assert spec.model_copy(update={k: getattr(base, k) for k in
                                   ("floors", "floor_heights_m", "eaves_m")}) == base


def _unfixed(elements):
    return [e.model_copy(update={"fixed": []}) for e in elements]


def _fixed(sheet):
    return sorted(e.cls for f in sheet.facades for e in f.elements if e.fixed)


def test_layout_stub_same_facades_in_both_modes(lay_out):
    """Стаб шага 4: заготовка простого дома, одна раскладка на оба режима; режимы отличаются
    только тем, что задано условием (`facade: Проёмы плана — условие`)."""
    plan_mode, blind = lay_out(Mode.WITH_OPENINGS), lay_out(Mode.BLIND)
    for a, b in zip(plan_mode.facades, blind.facades, strict=True):
        assert (_unfixed(a.elements), a.zones) == (_unfixed(b.elements), b.zones)
    windows = [e.w_m for f in blind.facades for e in f.elements if e.cls is ElementClass.WINDOW]
    assert sorted(windows) == [1.0, 1.2, 1.5, 2.0]  # окна простого дома — разного размера
    FacadeSheet.model_validate(blind.model_dump())  # материалы — из палитры стаба шага 1


def test_layout_stub_fixes_only_plan_openings(lay_out):
    """В глухом режиме окна плана заделаны — задан условием только вход; в «окна из плана» —
    все пять проёмов (`generation: Режимы отличаются входом`)."""
    assert _fixed(lay_out(Mode.BLIND)) == [ElementClass.DOOR]
    assert _fixed(lay_out(Mode.WITH_OPENINGS)) == [ElementClass.DOOR] + [ElementClass.WINDOW] * 4


def test_layout_stub_rejects_unknown_wall(lay_out, cfg):
    wall = lay_out().facades[1]
    longer = wall.model_copy(update={"side": wall.side.model_copy(update={"length_m": 7.0})})
    with pytest.raises(ModelError, match="стаб знает только простой дом"):
        house = stub.spec_model("", cfg.models.spec)
        stub.layout_model(longer, LayoutContext(house, Mode.WITH_OPENINGS, ""))


def test_layout_stub_rejects_other_number_of_walls(lay_out):
    sheet = lay_out()
    three = sheet.model_copy(update={"facades": sheet.facades[:3]})
    with pytest.raises(ModelError, match="из 4 стен, а у плана их 3"):
        stub.layout_all(three, LayoutContext(sheet.spec, Mode.WITH_OPENINGS, ""))
