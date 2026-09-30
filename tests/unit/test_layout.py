"""Правило шага 4: проёмы, декор, зоны отделки (generation.md, facade.md правило 9; gf#50)."""

from pathlib import Path

import pytest

from genfacade.layout.rule import LayoutContext, place
from genfacade.schema import EPS, FacadeSheet

EXAMPLE = Path(__file__).parents[2] / "materials" / "genplan-plan-example.svg"
CLASSIC = "Two-storey classic house with a gable roof."
MODERN = "Two-storey modern villa with a flat roof and panoramic windows."


def _of(sheet, cls):
    return [e for f in sheet.facades for e in f.elements if e.cls == cls]


def test_windows_stacked_on_every_floor(lay_out):
    sheet = lay_out(EXAMPLE, CLASSIC)
    for f in sheet.facades:
        by_floor = {}
        for w in (e for e in f.elements if e.cls == "window"):
            by_floor.setdefault(w.floor, []).append((w.x_m, w.w_m))
        assert len({tuple(v) for v in by_floor.values()}) <= 1  # одни и те же столбцы


def test_plan_fields_fixed_only_where_plan_sets_them(lay_out):
    sheet = lay_out(EXAMPLE, CLASSIC)
    windows = _of(sheet, "window")
    assert all(w.fixed == ["x_m", "w_m"] for w in windows if w.floor == 1)
    assert all(w.fixed == [] for w in windows if w.floor > 1)
    assert all(d.fixed == ["x_m", "w_m"] for d in _of(sheet, "door"))


@pytest.mark.parametrize("text", [CLASSIC, MODERN])
def test_windows_between_floor_and_lintel(lay_out, cfg, text):
    sheet = lay_out(EXAMPLE, text, mode="blind")
    spec, levels = sheet.spec, sheet.spec.floor_levels()
    for w in _of(sheet, "window"):
        base, top = levels[w.floor - 1], levels[w.floor]
        assert w.y_m >= base - EPS
        assert w.y_m + w.h_m <= top - cfg.layout.windows.lintel_m + EPS
    assert spec.floors == 2


def test_sills_and_casings_follow_style(lay_out):
    classic = lay_out(EXAMPLE, CLASSIC)
    windows = {w.id for w in _of(classic, "window")}
    assert {s.parent for s in _of(classic, "sill")} == windows
    assert {m.parent for m in _of(classic, "molding")} == windows
    panoramic = lay_out(EXAMPLE, MODERN)
    assert all(w.variant.kind == "panoramic" for w in _of(panoramic, "window"))
    assert _of(panoramic, "sill") == [] and _of(panoramic, "molding") == []
    # модерн с обычными окнами: подоконники есть, наличников у стиля нет
    modern = lay_out(EXAMPLE, "Two-storey modern villa with a flat roof.")
    assert _of(modern, "sill") and _of(modern, "molding") == []


def test_casing_drawn_under_its_window(lay_out):
    for f in lay_out(EXAMPLE, CLASSIC).facades:
        order = [e.id for e in f.elements]
        for m in (e for e in f.elements if e.cls == "molding"):
            assert order.index(m.id) < order.index(m.parent)


def test_zone_heights_same_on_all_sides(lay_out):
    """Цоколь, основная отделка и пояса — по отметкам HouseSpec: углы сходятся."""
    sheet = lay_out(EXAMPLE, CLASSIC)
    bands = [{(round(min(y for _, y in z.shape), 6), round(max(y for _, y in z.shape), 6))
              for z in f.zones if z.role in ("plinth", "main", "band")} for f in sheet.facades]
    assert all(b == bands[0] for b in bands)
    assert len([z for z in sheet.facades[0].zones if z.role == "band"]) == sheet.spec.floors - 1


def test_accent_gable_or_entrance(lay_out):
    gable = lay_out(EXAMPLE, CLASSIC)
    for f in gable.facades:
        accents = [z for z in f.zones if z.role == "accent"]
        has_gable = len(f.silhouette) == 5
        assert bool(accents) == has_gable
        assert all(min(y for _, y in z.shape) >= gable.spec.eaves_m - EPS for z in accents)
    flat = lay_out(EXAMPLE, MODERN)
    with_accent = [f.side.index for f in flat.facades if any(z.role == "accent" for z in f.zones)]
    assert with_accent == [0]  # только сторона входа


@pytest.mark.parametrize(("text", "size"), [("Cottage with small windows.", "small"),
                                            ("Cottage.", "standard"),
                                            ("Cottage with floor-to-ceiling glazing.", "high")])
def test_window_height_level_from_text(lay_out, cfg, text, size):
    sheet = lay_out(EXAMPLE, text)
    low, _ = cfg.layout.windows.size[size]
    base, fh = sheet.spec.plinth_m, sheet.spec.floor_heights_m[0]
    assert all(w.y_m == pytest.approx(base + low * fh) for w in _of(sheet, "window"))


def test_blind_rhythm_same_width_on_all_sides(lay_out):
    sheet = lay_out(EXAMPLE, CLASSIC, mode="blind", seed=5)
    assert len({round(w.w_m, 6) for w in _of(sheet, "window")}) == 1


def test_hand_written_palettes_get_roles(cfg, house):
    """Дом из тестовых JSON: палитра не по ролям — роли по порядку, без материала крыши."""
    ctx = LayoutContext(house.spec, "with_openings", "", 0)
    sheet = FacadeSheet.model_validate(house.model_copy(
        update={"facades": [place(f, ctx, cfg.layout) for f in house.facades]}).model_dump())
    used = {z.material for f in sheet.facades for z in f.zones}
    used |= {e.material for f in sheet.facades for e in f.elements if e.material}
    assert house.spec.roof.material not in used
