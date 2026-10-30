"""Синтетические дома: параметры дома и раскладка стен правилами
(`data: Синтетика своим генератором`)."""

import random
from itertools import combinations

import pytest

from genfacade import guidelines
from genfacade.datasets import store
from genfacade.datasets.synthetic import build, sizes
from genfacade.datasets.synthetic.house import Scheme, house
from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg
from genfacade.schema import (
    DOOR_KINDS,
    EPS,
    ElementClass,
    FixedField,
    OpeningKind,
    PaletteRole,
    Source,
    VariantKind,
    ZoneRole,
)
from genfacade.validate import OPENINGS, validate

SEEDS = range(60)
# Правила свода, которые генератор выполняет по построению (gf#211, config/guidelines.toml)
SVOD = {"window_head_line", "window_head_height_us", "window_head_to_eaves", "door_head_line",
        "window_lower_not_smaller", "pier_min", "window_types", "sill_under_window",
        "shutter_width_us"}


@pytest.fixture(scope="module")
def houses(cfg):
    return [build.sample(s, cfg) for s in SEEDS]


@pytest.fixture(scope="module")
def looks(cfg):
    """Параметры и характер дома по тем же seed, что у примеров."""
    return [house(random.Random(f"house/{s}"), cfg.synthetic,  # noqa: S311
                  sizes.pick(s, cfg.synthetic)) for s in SEEDS]


def _of(facade, cls):
    return [e for e in facade.elements if e.cls is cls]


def _walls(houses):
    return [(h, f) for h in houses for f in h.sheet.facades]


def test_every_house_passes_validator(houses, cfg):
    """Ни ошибок, ни предупреждений: окна разной высоты стоят верхом на одной линии."""
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


def test_upper_floors_get_windows_the_plan_does_not_give(houses):
    """`data: Этажность синтетики`: окна на каждом этаже стены с окнами плана, глухая стена глухая
    на всех этажах; место окна верхнего этажа ставит правило — оно не помечено заданным планом.
    Ряд верхнего этажа — по осям нижнего или свой; бывает и то, и другое."""
    kinds = set()
    for h, f in _walls(houses):
        windows, floors = _of(f, ElementClass.WINDOW), h.sheet.spec.floors
        rows = {n: sorted((w.x_m, w.w_m) for w in windows if w.floor == n)
                for n in range(1, floors + 1)}
        assert all(bool(row) == bool(rows[1]) for row in rows.values()), (h.id, f.side.index)
        assert all(not w.fixed for w in windows if w.floor > 1)
        assert all(rows[n] == rows[2] for n in range(3, floors + 1))  # третий повторяет второй
        if floors > 1 and rows[1]:
            kinds.add(rows[2] == rows[1])
    assert kinds == {True, False}


def test_door_kind_one_per_house_and_fits_under_cornice(houses, looks, cfg):
    """Вид двери — по характеру дома; верх двери — на линии окон (door_head_line, gf#211);
    фрамуга — только там, где полотно с ней не выше этой линии."""
    rules, kinds = cfg.synthetic.facade, set()
    for h, (spec, look) in zip(houses, looks, strict=True):
        [door] = [d for f in h.sheet.facades for d in _of(f, ElementClass.DOOR)]
        kind = door.variant.kind if door.variant else None
        kinds.add(kind)
        assert (door.y_m, door.h_m) == (spec.plinth_m, look.head_m)
        above = rules.entry.canopy_gap_m + rules.entry.canopy_m if look.canopy else 0.0
        assert door.y_m + door.h_m + above <= spec.eaves_m - rules.cornice.height_m + EPS, h.id
        if kind is not look.door:  # фрамуга не влезла — дверь со стеклом
            assert (look.door, kind) == (VariantKind.TRANSOM, VariantKind.GLAZED)
            assert look.head_m < rules.door.height_m + rules.door.transom_m
    assert kinds == {None, *DOOR_KINDS} and set(rules.door.weights) >= set(DOOR_KINDS)


def test_window_tops_align_and_heights_come_from_rows(houses, looks, cfg):
    """Верх окон каждого этажа — одна линия на дом под перемычкой; высота окна — по ширине: узкое
    маленькое, большое в пол (если так у дома), остальные — высота дома из ряда, при которой
    подоконник в пределах (gf#211, `data: Этажность синтетики` — так на каждом этаже)."""
    rules = cfg.synthetic.facade.windows
    for h, (spec, look) in zip(houses, looks, strict=True):
        under = spec.floor_heights_m[0] - rules.lintel_m  # перемычка до потолка этажа
        assert look.head_m == pytest.approx(min(look.head_m, under))
        assert rules.head_m[0] - EPS <= look.head_m <= rules.head_m[1] + EPS or (
            look.head_m == pytest.approx(under))
        assert look.window_h_m in rules.heights_m and look.narrow_h_m in rules.narrow_heights_m
        assert rules.sill_m[0] - EPS <= look.head_m - look.window_h_m <= rules.sill_m[1] + EPS
        levels = spec.floor_levels()
        for w in (w for f in h.sheet.facades for w in _of(f, ElementClass.WINDOW)):
            assert w.y_m + w.h_m == pytest.approx(levels[w.floor - 1] + look.head_m), (h.id, w.id)
            wide, narrow = w.w_m >= rules.wide_min_w_m, w.w_m <= rules.narrow_max_w_m
            want = (look.head_m if wide and look.wide_to_floor
                    else look.narrow_h_m if narrow else look.window_h_m)
            assert w.h_m == pytest.approx(want), (h.id, w.id)
            assert (w.variant.kind is VariantKind.PANORAMIC) == (want == look.head_m)


def test_shutters_beside_their_window(houses, looks, cfg):
    """Ставни — пара по бокам окна шириной share его ширины (shutter_width_us, gf#211), снаружи
    наличника, в пределах стены и не заходят на соседний проём и его ставни."""
    rules, casing = cfg.synthetic.facade.shutter, cfg.synthetic.facade.casing.width_m
    shuttered = 0
    for h, (_, look) in zip(houses, looks, strict=True):
        for f in h.sheet.facades:
            blinds, by_id = _of(f, ElementClass.BLIND), {e.id: e for e in f.elements}
            assert not blinds or look.shutters, h.id
            shuttered += bool(blinds)
            offset = casing if look.casing else 0.0
            for b in blinds:
                w = by_id[b.parent]
                assert w.cls is ElementClass.WINDOW and w.variant.kind is VariantKind.REGULAR
                assert (b.y_m, b.h_m, b.w_m) == (w.y_m, w.h_m, pytest.approx(rules.share * w.w_m))
                assert b.x_m + b.w_m == pytest.approx(w.x_m - offset) or (
                    b.x_m == pytest.approx(w.x_m + w.w_m + offset))
                assert -EPS <= b.x_m and b.x_m + b.w_m <= f.side.length_m + EPS
            busy = [*blinds, *(e for e in f.elements if e.cls in OPENINGS)]
            for a, b in combinations(busy, 2):
                apart = a.x_m + a.w_m <= b.x_m + EPS or b.x_m + b.w_m <= a.x_m + EPS
                assert apart or a.floor != b.floor, (h.id, a.id, b.id)
    assert shuttered > 0


def test_svod_rules_the_generator_applies_hold(houses, cfg):
    """Правила свода, которые генератор применяет по построению (gf#211), выполнены на каждом
    случае; вероятностные (окна этажей на осях, козырёк) — в docs/metrics-results.md."""
    sheets = [h.sheet for h in houses]
    for g in cfg.guidelines.guideline:
        if g.id in SVOD:
            cases = [ok for s in sheets for ok in guidelines.cases(g, s, None)]
            assert cases and all(cases), g.id
    assert SVOD <= {g.id for g in cfg.guidelines.guideline}


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
        plinth = {ZoneRole.PLINTH: (0, spec.plinth_m)} if spec.plinth_m > 0 else {}  # без цоколя
        assert spans == {**plinth, ZoneRole.MAIN: (spec.plinth_m, spec.eaves_m)}
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
                           or b[3] <= w.y_m + EPS or b[1] >= w.y_m + w.h_m - EPS
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
            # крыльцо — на высоту цоколя: без цоколя его нет
            assert len(porch) == (look.porch and f.side.has_entrance and spec.plinth_m > 0), h.id
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
    for seed, (spec, _) in zip(SEEDS, looks, strict=True):
        size = sizes.pick(seed, cfg.synthetic)  # высота этажа и цоколь — из профиля дома
        assert spec.floor_heights_m[0] in sizes.grid(size.floor_height_m, size.floor_height_step_m)
        assert spec.style in rules.styles
        assert size.plinth_m[0] <= spec.plinth_m <= size.plinth_m[1]
        assert spec.eaves_m == pytest.approx(spec.plinth_m + sum(spec.floor_heights_m))
        assert len(set(spec.floor_heights_m)) == 1  # высота этажа одна на дом
        kinds = {m.id: m.kind for m in spec.materials}
        assert set(kinds) == set(PaletteRole)
        assert all(kinds[r] in rules.palette[r] and kinds[r] in cfg.library.kinds for r in kinds)
        walls = [kinds[r] for r in (PaletteRole.MAIN, PaletteRole.PLINTH, PaletteRole.ACCENT)]
        assert len(set(walls)) == 3  # цоколь и акцент не сливаются с основной отделкой


def test_houses_differ_in_character(looks, cfg):
    specs = [spec for spec, _ in looks]
    assert {s.style for s in specs} == set(cfg.synthetic.spec.styles)
    gp = cfg.synthetic.sizes.genplan  # в основных настройках — только профиль GenPlan (gf#186)
    assert {s.floor_heights_m[0] for s in specs} == set(sizes.grid(gp.floor_height_m,
                                                                     gp.floor_height_step_m))
    assert {s.floors for s in specs} == set(range(1, len(cfg.synthetic.spec.floors_weights) + 1))
    windows = cfg.synthetic.facade.windows
    assert len({look.head_m for _, look in looks}) > 3  # верх окон — не три уровня, как было
    assert {look.window_h_m for _, look in looks} == set(windows.heights_m)
    assert {look.scheme for _, look in looks} == set(Scheme)
    for flag in ("casing", "wide_to_floor", "porch", "canopy", "shutters"):
        assert {getattr(look, flag) for _, look in looks} == {True, False}, flag


def test_sheets_survive_svg(houses, cfg):
    """JSON → SVG → разбор SVG даёт те же элементы и зоны (`facade: JSON и SVG — одно содержимое`) —
    на домах со всеми видами дверей, крыльцом и козырьком."""
    for h in houses[:20]:
        parsed = parse_sheet_svg(sheet_svg(h.sheet, cfg))
        assert [parsed[f.side.index] for f in h.sheet.facades] == [
            (f.elements, f.zones) for f in h.sheet.facades], h.id


def test_manifest_counts_blind_walls(houses, tmp_path):
    for h in houses[:10]:
        store.write(h, tmp_path)
    blind = sum(not f.side.openings for h in houses[:10] for f in h.sheet.facades)
    assert 0 < store.manifest(tmp_path, Source.SYNTHETIC)["blind_walls"] == blind < 40
