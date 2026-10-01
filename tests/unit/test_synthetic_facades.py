"""Синтетические дома: параметры дома и раскладка стен правилами (data.md, правило 1)."""

import random

import pytest

from genfacade.datasets import store
from genfacade.datasets.synthetic import build
from genfacade.datasets.synthetic.house import Scheme, house
from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg
from genfacade.schema import (
    EPS,
    ElementClass,
    FixedField,
    OpeningKind,
    PaletteRole,
    Rule,
    Severity,
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
    """Ошибок нет. Предупреждение одно и намеренное: окна этажа разной высоты."""
    found = [(h.id, v) for h in houses for v in validate(h.sheet, cfg.checks)]
    assert [(i, v.message) for i, v in found if v.severity is Severity.ERROR] == []
    assert {v.rule for _, v in found} == {Rule.FLOOR_ALIGN}


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


def test_window_tops_align_and_sills_follow_width(houses, looks, cfg):
    """Верх окон дома один; низ — по ширине: узкое высоко, большое в пол, остальные по уровню."""
    rules = cfg.synthetic.facade.windows
    for h, (spec, look) in zip(houses, looks, strict=True):
        windows = [w for f in h.sheet.facades for w in _of(f, ElementClass.WINDOW)]
        height = spec.floor_heights_m[0]
        top = spec.plinth_m + min(look.window_span[1] * height, height - rules.lintel_m)
        assert {round(w.y_m + w.h_m, 3) for w in windows} == {round(top, 3)}, h.id
        for w in windows:
            low = (w.y_m - spec.plinth_m) / spec.floor_heights_m[0]
            wide, narrow = w.w_m >= rules.wide_min_w_m, w.w_m <= rules.narrow_max_w_m
            want = (0.0 if wide and look.wide_to_floor
                    else max(rules.narrow_low, look.window_span[0]) if narrow
                    else look.window_span[0])
            assert low == pytest.approx(want, abs=1e-3), (h.id, w.id)
            assert (w.variant.kind is VariantKind.PANORAMIC) == (want == 0.0)


def test_sills_and_casings_only_at_windows_with_sill_wall(houses, looks):
    for h, (_, look) in zip(houses, looks, strict=True):
        for f in h.sheet.facades:
            framed = {w.id for w in _of(f, ElementClass.WINDOW)
                      if w.variant.kind is not VariantKind.PANORAMIC}
            assert {s.parent for s in _of(f, ElementClass.SILL)} == framed, h.id
            casings = _of(f, ElementClass.MOLDING)
            assert {m.parent for m in casings} == (framed if look.casing else set())
            order = [e.id for e in f.elements]  # наличник рисуется под своим окном
            assert all(order.index(m.id) < order.index(m.parent) for m in casings)


def test_houses_mix_window_heights(houses):
    """Окна разной высоты на одном доме — не редкость, но и не у каждого (хозяин 01.10)."""
    mixed = sum(len({w.y_m for f in h.sheet.facades for w in _of(f, ElementClass.WINDOW)}) > 1
                for h in houses)
    assert 0.15 * len(houses) < mixed < 0.9 * len(houses)


def _accents(facade):
    return [(min(x for x, _ in z.shape), min(y for _, y in z.shape),
             max(x for x, _ in z.shape), max(y for _, y in z.shape))
            for z in facade.zones if z.role is ZoneRole.ACCENT]


def test_base_zones_meet_at_corners(houses):
    for h, f in _walls(houses):
        spec = h.sheet.spec
        spans = {z.role: (min(y for _, y in z.shape), max(y for _, y in z.shape))
                 for z in f.zones if z.role is not ZoneRole.ACCENT}
        assert spans == {ZoneRole.PLINTH: (0, spec.plinth_m),
                         ZoneRole.MAIN: (spec.plinth_m, spec.eaves_m)}
        assert all(z.material == z.role for z in f.zones)  # материал — своя роль палитры


def test_accent_follows_house_scheme(houses, looks, cfg):
    finish = cfg.synthetic.facade.finish
    seen = set()
    for h, (spec, look) in zip(houses, looks, strict=True):
        for f in h.sheet.facades:
            boxes, length = _accents(f), f.side.length_m
            doors, windows = _of(f, ElementClass.DOOR), _of(f, ElementClass.WINDOW)
            if look.scheme is Scheme.PLAIN:
                assert boxes == []
            elif look.scheme is Scheme.ENTRANCE:
                assert len(boxes) == len(doors)
                assert all(b[0] <= d.x_m and b[2] >= d.x_m + d.w_m
                           for b, d in zip(boxes, doors, strict=True))
            elif look.scheme is Scheme.WAINSCOT:  # пояс одной высоты на всех стенах
                assert boxes == [(0.0, spec.plinth_m, length, spec.plinth_m + look.wainscot_m)]
            elif look.scheme is Scheme.CORNERS:
                assert [(b[0], b[2]) for b in boxes] == [
                    (0.0, finish.corner_m), (length - finish.corner_m, length)]
            else:  # вставки стоят в простенках: не заходят на окна
                assert len(boxes) <= max(0, len(windows) - 1)
                assert all(b[2] <= w.x_m + EPS or b[0] >= w.x_m + w.w_m - EPS
                           for b in boxes for w in windows)
                assert all(b[2] - b[0] <= finish.pier_max_m + EPS for b in boxes)
            seen.add((look.scheme, bool(boxes)))
    assert {s for s, drawn in seen if drawn} == set(Scheme) - {Scheme.PLAIN}
    assert set(finish.weights) == {s.value for s in Scheme}  # у каждой схемы есть вес в config


def test_porch_and_canopy_at_entrance(houses, looks, cfg):
    entry = cfg.synthetic.facade.entry
    for h, (spec, look) in zip(houses, looks, strict=True):
        for f in h.sheet.facades:
            porch, canopy = _of(f, ElementClass.PORCH), _of(f, ElementClass.CANOPY)
            assert len(porch) == (look.porch and f.side.has_entrance), h.id
            assert len(canopy) == (look.canopy and f.side.has_entrance), h.id
            for door in _of(f, ElementClass.DOOR):
                for p in porch:
                    assert (p.y_m, p.h_m, p.parent) == (0.0, spec.plinth_m, door.id)
                    assert p.x_m < door.x_m and p.x_m + p.w_m > door.x_m + door.w_m
                for k in canopy:
                    assert k.y_m == pytest.approx(door.y_m + door.h_m + entry.canopy_gap_m)
                    assert k.y_m + k.h_m <= spec.eaves_m + EPS and k.parent == door.id


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
    assert {look.scheme for _, look in looks} == set(Scheme)
    for flag in ("casing", "wide_to_floor", "porch", "canopy"):
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
