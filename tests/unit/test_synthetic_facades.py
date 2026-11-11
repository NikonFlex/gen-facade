"""Синтетические дома: параметры дома и раскладка стен правилами
(`data: Синтетика своим генератором`)."""

import random
from itertools import combinations
from xml.etree import ElementTree

import pytest
import shapely

from genfacade import guidelines, roof, window_shape
from genfacade.datasets import store
from genfacade.datasets.synthetic import build, sizes
from genfacade.datasets.synthetic.house import Scheme, house
from genfacade.render import sheet_format
from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg
from genfacade.schema import (
    DOOR_KINDS,
    EPS,
    ElementClass,
    FixedField,
    OpeningKind,
    PaletteRole,
    RoofKind,
    Rule,
    Source,
    Trim,
    VariantKind,
    ZoneRole,
)
from genfacade.validate import OPENINGS, validate

SEEDS = range(60)
# Правила свода, которые генератор выполняет по построению (gf#211, config/guidelines.toml). Не по
# построению (gf#212): window_head_height_us — на этаже 2,5 м с наличником верх окон ниже 2,1 м,
# чтобы над окном остался фриз до карниза (window_head_to_eaves); sill_under_window — подоконников
# у дома может не быть, их вид — параметр дома.
SVOD = {"window_head_line", "window_head_to_eaves", "door_head_line",
        "window_lower_not_smaller", "pier_min", "window_types", "shutter_width_us"}


@pytest.fixture(scope="module")
def houses(rect_cfg):
    return [build.sample(s, rect_cfg) for s in SEEDS]


@pytest.fixture(scope="module")
def gable_cfg(rect_cfg):
    """Окна во фронтоне и по скату — у большинства домов (доли до gf#373): у домов с долями по
    настоящим домам их в 60 домах слишком мало для проверки формы наличника."""
    gable = rect_cfg.synthetic.facade.gable
    rich = gable.model_copy(update={"share": 0.9, "shapes": {**gable.shapes,
                                                              VariantKind.SLOPE: 50}})
    facade = rect_cfg.synthetic.facade.model_copy(update={"gable": rich})
    return rect_cfg.model_copy(update={
        "synthetic": rect_cfg.synthetic.model_copy(update={"facade": facade})})


@pytest.fixture(scope="module")
def gable_houses(gable_cfg):
    return [build.sample(s, gable_cfg) for s in SEEDS]


@pytest.fixture(scope="module")
def looks(cfg):
    """Параметры и характер дома по тем же seed, что у примеров."""
    return [house(random.Random(f"house/{s}"), cfg,  # noqa: S311
                  sizes.pick(s, cfg.synthetic)) for s in SEEDS]


def _of(facade, cls):
    return [e for e in facade.elements if e.cls is cls]


def _walls(houses):
    return [(h, f) for h in houses for f in h.sheet.facades]


@pytest.mark.slow
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


def _roofed(f, spec):
    """Окна во фронтоне — этажа под скатом (gf#321)."""
    return [w for w in _of(f, ElementClass.WINDOW) if w.floor > spec.floors]


def test_windows_between_floor_and_cornice(houses, cfg):
    """Окна этажей — между полом и карнизом; стена с окнами во фронтоне — щипцовая, без карниза
    (gf#321)."""
    rules = cfg.synthetic.facade
    for h, f in _walls(houses):
        spec = h.sheet.spec
        roofed = _roofed(f, spec)
        if roofed:
            assert not _of(f, ElementClass.CORNICE)
        else:
            [cornice] = _of(f, ElementClass.CORNICE)
            assert (cornice.x_m, cornice.w_m) == (0.0, f.side.length_m)
            assert cornice.y_m + cornice.h_m == pytest.approx(spec.eaves_m)
        for w in _of(f, ElementClass.WINDOW):
            if w in roofed:
                continue
            assert w.y_m >= spec.plinth_m - EPS, h.id
            assert w.y_m + w.h_m <= spec.eaves_m - rules.windows.lintel_m + EPS, h.id


def test_gable_windows_stand_in_the_gable_off_the_slope(houses, rect_cfg):
    """`data: Синтетика своим генератором` (gf#321): окна во фронтоне — у части домов с двускатной
    крышей, только на щипцовых стенах, в стене с отступом от ската, одного из типоразмеров окон
    этажей дома; при доле ноль дома прежние."""
    cfg = rect_cfg
    rules, roofed = cfg.synthetic.facade.gable, []
    for h in houses:
        spec, gables = h.sheet.spec, roof.gables(h.sheet)
        for f, above in zip(h.sheet.facades, gables, strict=True):
            for w in _roofed(f, spec):
                assert spec.roof.kind is RoofKind.GABLE and above is not None, h.id
                room = roof.room(f.side.length_m, spec.eaves_m, above, cfg.checks.slope_offset_m)
                frame = shapely.box(w.x_m, w.y_m, w.x_m + w.w_m, w.y_m + w.h_m)
                if w.variant is not None and w.variant.kind is VariantKind.SLOPE:
                    continue  # рамка через скат — контур, `test_slope_windows_cross_the_slope`
                assert room.buffer(EPS).contains(frame), h.id
                low, high = rules.sill_m
                assert low - EPS <= w.y_m - spec.eaves_m <= high + EPS
                roofed.append(h.id)
    assert roofed  # у части домов окна во фронтоне есть
    zero = cfg.synthetic.model_copy(update={"facade": cfg.synthetic.facade.model_copy(
        update={"gable": rules.model_copy(update={"share": 0.0})})})
    flat = cfg.model_copy(update={"synthetic": zero})
    for h in houses:
        if h.id in roofed:
            plain = build.sample(int(h.id.split("-")[1]), flat)
            assert not any(_roofed(f, plain.sheet.spec) for f in plain.sheet.facades)
            assert plain.plan == h.plan


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
        canopy = [k for f in h.sheet.facades for k in _of(f, ElementClass.CANOPY)]
        top = max([door.y_m + door.h_m, *(k.y_m + k.h_m for k in canopy)])
        assert top <= spec.eaves_m - look.cornice_m + EPS, h.id  # козырёк — под карнизом
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
        assert look.head_m <= under + EPS
        assert look.head_m <= rules.head_m[1] + EPS
        assert look.window_h_m in rules.heights_m and look.narrow_h_m in rules.narrow_heights_m
        assert rules.sill_m[0] - EPS <= look.head_m - look.window_h_m <= rules.sill_m[1] + EPS
        levels = spec.floor_levels()
        for w in (w for f in h.sheet.facades for w in _of(f, ElementClass.WINDOW)
                  if w.floor <= h.sheet.spec.floors):  # окно во фронтоне — не этажа
            assert w.y_m + w.h_m == pytest.approx(levels[w.floor - 1] + look.head_m), (h.id, w.id)
            wide, narrow = w.w_m >= rules.wide_min_w_m, w.w_m <= rules.narrow_max_w_m
            want = (look.head_m if wide and look.wide_to_floor
                    else look.narrow_h_m if narrow else look.window_h_m)
            assert w.h_m == pytest.approx(want), (h.id, w.id)
            assert (w.variant.kind is VariantKind.PANORAMIC) == (want == look.head_m)


def test_shutters_beside_their_window(houses):
    """Ставни — у дома с ними, у окна не в пол; ставни разных проёмов этажа не сходятся
    (геометрия — tests/unit/test_derive.py)."""
    shuttered = 0
    for h in houses:
        for f in h.sheet.facades:
            blinds, by_id = _of(f, ElementClass.BLIND), {e.id: e for e in f.elements}
            assert not blinds or h.sheet.spec.trim.has(Trim.SHUTTERS), h.id
            shuttered += bool(blinds)
            for b in blinds:
                w = by_id[b.parent]
                assert w.cls is ElementClass.WINDOW and w.variant.kind is VariantKind.REGULAR
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


def test_sills_and_casings_only_at_windows_with_sill_wall(houses):
    """Подоконник и наличник — у каждого окна не в пол, если такие у дома есть (вид — параметр
    дома, gf#212); наличник рисуется под своим окном."""
    for h in houses:
        trim = h.sheet.spec.trim
        for f in h.sheet.facades:
            framed = {w.id for w in _of(f, ElementClass.WINDOW)
                      if w.variant.kind is not VariantKind.PANORAMIC}
            sills = {s.parent for s in _of(f, ElementClass.SILL)}
            assert sills == (framed if trim.has(Trim.SILL) else set()), h.id
            casings = _of(f, ElementClass.MOLDING)
            assert {m.parent for m in casings} == (framed if trim.has(Trim.CASING) else set())
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


def test_porch_and_canopy_at_entrance(houses, looks):
    for h, (spec, look) in zip(houses, looks, strict=True):
        for f in h.sheet.facades:
            porch, canopy = _of(f, ElementClass.PORCH), _of(f, ElementClass.CANOPY)
            # крыльцо — на высоту цоколя: без цоколя его нет
            assert len(porch) == (look.porch and f.side.has_entrance and spec.plinth_m > 0), h.id
            assert len(canopy) <= (spec.trim.has(Trim.CANOPY) and f.side.has_entrance), h.id
            for door in _of(f, ElementClass.DOOR):
                for p in porch:
                    assert (p.y_m, p.h_m, p.parent) == (0.0, spec.plinth_m, door.id)
                    assert p.x_m < door.x_m and p.x_m + p.w_m > door.x_m + door.w_m
                for k in canopy:
                    assert k.y_m > door.y_m + door.h_m and k.parent == door.id


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
    for flag in ("wide_to_floor", "porch"):
        assert {getattr(look, flag) for _, look in looks} == {True, False}, flag
    for trim in Trim:  # виды выводимых элементов — все, что в весах генератора (gf#212)
        kinds = {spec.trim.kind(trim) for spec, _ in looks}
        assert kinds == set(getattr(cfg.synthetic.facade.trim, trim)), trim


@pytest.mark.slow
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


@pytest.mark.slow
def test_slope_windows_cross_the_slope_and_zero_share_keeps_the_houses(houses, rect_cfg):
    """`data: Синтетика своим генератором` (gf#319): окно во фронтоне вида `slope` — рамка выходит
    за скат, контур не меньше `slope_share` рамки, дом проходит валидатор (в том числе наличник по
    контуру); при весе `slope` ноль дома прежние байт в байт."""
    cfg, crossed = rect_cfg, []
    for h in houses:
        for f, above in zip(h.sheet.facades, roof.gables(h.sheet), strict=True):
            for w in _roofed(f, h.sheet.spec):
                if w.variant is None or w.variant.kind is not VariantKind.SLOPE:
                    continue
                room = roof.room(f.side.length_m, h.sheet.spec.eaves_m, above,
                                 cfg.checks.slope_offset_m)
                frame = shapely.box(w.x_m, w.y_m, w.x_m + w.w_m, w.y_m + w.h_m)
                assert not room.contains(frame)
                assert room.intersection(frame).area >= cfg.checks.slope_share * frame.area
                crossed.append(h.id)
        assert not [v for v in validate(h.sheet, cfg.checks)
                    if v.rule in (Rule.OUTSIDE, Rule.SLOPE)], h.id
    assert crossed
    gable = cfg.synthetic.facade.gable

    def without(shapes: dict) -> object:
        facade = cfg.synthetic.facade.model_copy(
            update={"gable": gable.model_copy(update={"shapes": shapes})})
        return cfg.model_copy(update={"synthetic": cfg.synthetic.model_copy(
            update={"facade": facade})})

    zero = without({k: (0.0 if k is VariantKind.SLOPE else v) for k, v in gable.shapes.items()})
    absent = without({k: v for k, v in gable.shapes.items() if k is not VariantKind.SLOPE})
    for h in houses:  # вес ноль — как без вида: дома прежние (сверено и со старым кодом, 08.11)
        seed = int(h.id.split("-")[1])
        plain = build.sample(seed, zero)
        assert plain.sheet.model_dump_json() == build.sample(seed, absent).sheet.model_dump_json()
        assert not any(w.variant is not None and w.variant.kind is VariantKind.SLOPE
                       for f in plain.sheet.facades for w in _roofed(f, plain.sheet.spec))


def test_casing_of_a_slope_window_follows_the_window_outline(gable_houses, gable_cfg):
    """Наличник окна по скату (gf#319): на листе — контур вокруг контура окна, прямоугольник
    остаётся невидимой рамкой для разбора; проверка стены — по контуру, не по прямоугольнику."""
    found = 0
    for h in gable_houses:
        sheet = h.sheet
        for k, f in enumerate(sheet.facades):
            slopes = {w.id for w in _roofed(f, sheet.spec)
                      if w.variant is not None and w.variant.kind is VariantKind.SLOPE}
            casings = [e for e in f.elements
                       if e.cls is ElementClass.MOLDING and e.parent in slopes]
            if not casings:
                continue
            found += len(casings)
            text = sheet_svg(sheet, gable_cfg)
            assert parse_sheet_svg(text)[k][0] == f.elements
            nodes = list(ElementTree.fromstring(text).iter())
            above = roof.gables(sheet)[k]
            room = roof.room(f.side.length_m, sheet.spec.eaves_m, above,
                             gable_cfg.checks.slope_offset_m)
            for e in casings:
                at = next(i for i, n in enumerate(nodes) if n.get(sheet_format.ID) == e.id)
                parent = next(w for w in f.elements if w.id == e.parent)
                raw = nodes[at + 1].get("points").split()
                drawn = [tuple(map(float, p.split(","))) for p in raw]
                want = window_shape.casing(parent, e, room)
                assert nodes[at].get("class") == "trim-frame"
                assert shapely.Polygon(drawn).equals_exact(shapely.Polygon(want), 0.01), e.id
    assert found


# Настоящие 47 домов (data/samples/manual), датчик tools/shares_probe.py, gf#373: у 8 из 21 домов с
# двускатной крышей и щипцом окно выше карниза (бутстреп по домам, 2,5–97,5 %: 0,19–0,57); окон по
# скату — 3 из 21 окна выше карниза; двускатных среди скатных домов 26 из 35.
REAL_GABLE_HOUSES = (0.19, 0.57)
REAL_SLOPE_OF_GABLE_WINDOWS = 3 / 21
REAL_GABLE_OF_SLOPED = 26 / 35


def test_gable_shares_stay_within_real_houses(cfg):
    """`data: Синтетика своим генератором` (gf#373): доли окон во фронтоне генератора — как у
    настоящих домов. У реального щипца места много, окно влезает всегда, поэтому модель повторяет
    не долю синтетики, а долю генератора на просторном щипце: дом с окнами — `share` и хотя бы одно
    окно на торце (не нуль в `count_weights`); окно по скату — доля веса `slope`."""
    rules = cfg.synthetic.facade.gable
    roomy = rules.share * (1 - rules.count_weights[0] / sum(rules.count_weights))
    assert REAL_GABLE_HOUSES[0] <= roomy <= REAL_GABLE_HOUSES[1]
    slope = rules.shapes[VariantKind.SLOPE] / sum(rules.shapes.values())
    assert slope <= 2 * REAL_SLOPE_OF_GABLE_WINDOWS  # не втрое чаще настоящих, как при весе 50
    roofs = cfg.synthetic.spec.roof_weights
    sloped = {k: w for k, w in roofs.items() if k is not RoofKind.FLAT}
    assert roofs[RoofKind.GABLE] / sum(sloped.values()) >= 0.9 * REAL_GABLE_OF_SLOPED
