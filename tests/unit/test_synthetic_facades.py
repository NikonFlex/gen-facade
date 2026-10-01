"""Синтетические дома: параметры дома и раскладка стен правилами (data.md, правило 1)."""

import random

import pytest

from genfacade.datasets import store
from genfacade.datasets.synthetic import build
from genfacade.datasets.synthetic.house import house
from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg
from genfacade.schema import (
    EPS,
    ElementClass,
    FixedField,
    OpeningKind,
    PaletteRole,
    Source,
    VariantKind,
    ZoneRole,
)
from genfacade.validate import validate

SEEDS = range(60)


@pytest.fixture(scope="module")
def houses(cfg):
    return [build.sample(s, cfg) for s in SEEDS]


@pytest.fixture(scope="module")
def looks(cfg):
    """Параметры и характер дома по тем же seed, что у примеров."""
    return [house(random.Random(f"house/{s}"), cfg.synthetic) for s in SEEDS]  # noqa: S311


def _of(facade, cls):
    return [e for e in facade.elements if e.cls is cls]


def _walls(houses):
    return [(h, f) for h in houses for f in h.sheet.facades]


def test_every_house_passes_validator(houses, cfg):
    assert [(h.id, v.message) for h in houses for v in validate(h.sheet, cfg.checks)] == []


def test_plan_openings_stand_where_plan_put_them(houses):
    """Режим 2 в эталоне: место и ширина проёма — из плана и помечены как заданные."""
    for h, f in _walls(houses):
        wanted = {OpeningKind.WINDOW: ElementClass.WINDOW}
        placed = sorted((e.cls, e.x_m, e.w_m) for e in f.elements if e.fixed)
        plan = sorted((wanted.get(o.kind, ElementClass.DOOR), o.x_m, o.width_m)
                      for o in f.side.openings)
        assert placed == plan, (h.id, f.side.index)
        assert all(e.fixed == [FixedField.X, FixedField.W] for e in f.elements if e.fixed)
        assert bool(_of(f, ElementClass.DOOR)) == f.side.has_entrance


def test_windows_between_floor_and_cornice(houses, cfg):
    rules = cfg.synthetic.facade
    for h, f in _walls(houses):
        spec = h.sheet.spec
        [cornice] = _of(f, ElementClass.CORNICE)
        assert (cornice.x_m, cornice.w_m) == (0.0, f.side.length_m)
        assert cornice.y_m + cornice.h_m == pytest.approx(spec.eaves_m)
        for w in _of(f, ElementClass.WINDOW):
            assert w.y_m >= spec.plinth_m - EPS, h.id
            assert w.y_m + w.h_m <= spec.eaves_m - rules.windows.lintel_m + EPS, h.id
        for d in _of(f, ElementClass.DOOR):
            assert (d.y_m, d.h_m) == (spec.plinth_m, rules.door.height_m)


def test_one_window_character_per_house(houses, looks):
    """Высота окон, подоконники и наличники — одни на все стены дома (generation.md, п. 3)."""
    for h, (_, look) in zip(houses, looks, strict=True):
        windows = [w for f in h.sheet.facades for w in _of(f, ElementClass.WINDOW)]
        assert len({(w.y_m, w.h_m, w.variant.kind) for w in windows}) == 1, h.id
        spec = h.sheet.spec  # низ окна — доля высоты этажа от его пола, по уровню дома
        low = spec.plinth_m + look.window_span[0] * spec.floor_heights_m[0]
        assert windows[0].y_m == pytest.approx(low, abs=1e-3), h.id
        panoramic = windows[0].variant.kind is VariantKind.PANORAMIC
        assert panoramic == (look.window_span[0] == 0.0)
        for f in h.sheet.facades:
            framed = {w.id for w in _of(f, ElementClass.WINDOW)} if not panoramic else set()
            assert {s.parent for s in _of(f, ElementClass.SILL)} == framed
            casings = _of(f, ElementClass.MOLDING)
            assert {m.parent for m in casings} == (framed if look.casing else set())
            order = [e.id for e in f.elements]  # наличник рисуется под своим окном
            assert all(order.index(m.id) < order.index(m.parent) for m in casings)


def test_zones_meet_at_corners_and_accent_marks_entrance(houses, looks):
    for h, (_, look) in zip(houses, looks, strict=True):
        spec = h.sheet.spec
        for f in h.sheet.facades:
            spans = {z.role: (min(y for _, y in z.shape), max(y for _, y in z.shape))
                     for z in f.zones}
            assert spans[ZoneRole.PLINTH] == (0, spec.plinth_m)
            assert spans[ZoneRole.MAIN] == (spec.plinth_m, spec.eaves_m)
            assert (ZoneRole.ACCENT in spans) == (look.accent and f.side.has_entrance), h.id
            assert all(z.material == z.role for z in f.zones)  # материал — своя роль палитры


def test_house_parameters_come_from_config(looks, cfg):
    rules = cfg.synthetic.spec
    for spec, _ in looks:
        assert spec.floor_heights_m[0] in rules.floor_heights_m and spec.style in rules.styles
        assert rules.plinth_m[0] <= spec.plinth_m <= rules.plinth_m[1]
        assert spec.eaves_m == pytest.approx(spec.plinth_m + spec.floor_heights_m[0])
        kinds = {m.id: m.kind for m in spec.materials}
        assert set(kinds) == set(PaletteRole)
        assert all(kinds[r] in rules.palette[r] and kinds[r] in cfg.library.kinds for r in kinds)
        walls = [kinds[r] for r in (PaletteRole.MAIN, PaletteRole.PLINTH, PaletteRole.ACCENT)]
        assert len(set(walls)) == 3  # цоколь и акцент не сливаются с основной отделкой


def test_houses_differ_in_character(looks, cfg):
    specs = [spec for spec, _ in looks]
    assert {s.style for s in specs} == set(cfg.synthetic.spec.styles)
    assert {s.floor_heights_m[0] for s in specs} == set(cfg.synthetic.spec.floor_heights_m)
    spans = set(cfg.synthetic.facade.windows.size.values())
    assert {look.window_span for _, look in looks} == spans
    for flag in ("casing", "accent"):
        assert {getattr(look, flag) for _, look in looks} == {True, False}, flag


def test_sheet_survives_svg(houses, cfg):
    """JSON → SVG → разбор SVG даёт те же элементы и зоны (facade.md, критерии приёмки)."""
    sheet = houses[0].sheet
    parsed = parse_sheet_svg(sheet_svg(sheet, cfg))
    assert [parsed[f.side.index] for f in sheet.facades] == [
        (f.elements, f.zones) for f in sheet.facades]


def test_manifest_counts_blind_walls(houses, tmp_path):
    for h in houses[:10]:
        store.write(h, tmp_path)
    blind = sum(not f.side.openings for h in houses[:10] for f in h.sheet.facades)
    assert 0 < store.manifest(tmp_path, Source.SYNTHETIC)["blind_walls"] == blind < 40
