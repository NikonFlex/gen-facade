"""Стабы моделей шагов 1 и 4 (genfacade/models/stub.py, gf#60)."""

import pytest

from genfacade.models import stub
from genfacade.models.stub import LayoutContext, ModelError
from genfacade.schema import FacadeSheet


def test_spec_stub_ignores_text():
    """Стаб шага 1: одна спека на любой текст — один этаж, плоская крыша."""
    a, b = stub.spec_model("Five-storey apartment block."), stub.spec_model("")
    assert a == b and (a.floors, a.roof.kind) == (1, "flat")
    assert [m.id for m in a.materials] == ["main", "plinth", "accent", "trim", "roof"]


def test_layout_stub_same_facades_in_both_modes(lay_out):
    """Стаб шага 4: заготовка простого дома, один набор на оба режима."""
    plan_mode, blind = lay_out("with_openings"), lay_out("blind")
    for a, b in zip(plan_mode.facades, blind.facades, strict=True):
        assert (a.elements, a.zones) == (b.elements, b.zones)
    windows = [e.w_m for f in blind.facades for e in f.elements if e.cls == "window"]
    assert sorted(windows) == [1.0, 1.2, 1.5, 2.0]  # окна простого дома — разного размера
    FacadeSheet.model_validate(blind.model_dump())  # материалы — из палитры стаба шага 1


def test_layout_stub_rejects_unknown_wall(lay_out):
    wall = lay_out().facades[1]
    longer = wall.model_copy(update={"side": wall.side.model_copy(update={"length_m": 7.0})})
    with pytest.raises(ModelError, match="стаб знает только простой дом"):
        stub.layout_model(longer, LayoutContext(stub.spec_model(""), "with_openings", ""))


def test_layout_stub_rejects_other_number_of_walls(lay_out):
    sheet = lay_out()
    three = sheet.model_copy(update={"facades": sheet.facades[:3]})
    with pytest.raises(ModelError, match="из 4 стен, а у плана их 3"):
        stub.layout_all(three, LayoutContext(sheet.spec, "with_openings", ""))
