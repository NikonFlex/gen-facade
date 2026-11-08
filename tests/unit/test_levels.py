"""Окна, карниз, цоколь и низ двери — по параметрам дома (gf#272, gf#275, `facade: Высоты цоколя
и карниза — из параметров`, `facade: Нуль отметок — земля`, `generation: Привязка к сетке`): шаг 5
ставит их на отметки дома, что бы ни ответила модель шага 4. Дом — простой из conftest: цоколь
0,5 м, карниз 3,25 м, дверь на стороне 0.
"""

import pytest
from simple_house import whole_main, with_side, without_porches

from genfacade.levels import levels
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FixedField,
    MaterialZone,
    OpeningVariant,
    PaletteRole,
    RoofKind,
    Rule,
    VariantKind,
    ZoneRole,
)
from genfacade.snap import snap
from genfacade.validate import errors, validate

DOOR_SIDE = 0


def _of(f, cls):
    return [e for e in f.elements if e.cls is cls]


def _plinths(f):
    return [z for z in f.zones if z.role is ZoneRole.PLINTH]


def _top(z):
    return max(y for _, y in z.shape)


def _clean(sheet, cfg):
    assert errors(validate(sheet, cfg.checks)) == []
    return sheet


def test_clean_house_stays_as_is(house, cfg):
    """У стаба шага 4 всё уже на отметках дома — шаг 5 ничего не трогает, кроме крыльца: у двери
    на поднятом полу его ставит код (gf#276)."""
    got = snap(house, cfg.checks)
    assert without_porches(got) == house
    assert len(_of(got.facades[DOOR_SIDE], ElementClass.PORCH)) == 1


def test_cornice_piece_becomes_full_wall_under_eaves(house, cfg):
    """Карниз куском посреди стены и ниже отметки карниза — один карниз во всю стену под ней,
    высотой, как у карнизов дома."""
    f = house.facades[1]
    c = _of(f, ElementClass.CORNICE)[0]
    pieces = [c.model_copy(update={"x_m": 1.0, "w_m": 2.0, "y_m": 2.6}),
              c.model_copy(update={"id": "c2", "x_m": 3.5, "w_m": 1.0, "y_m": 2.7})]
    rest = [e for e in f.elements if e.cls is not ElementClass.CORNICE]
    got = _clean(snap(with_side(house, 1, elements=[*rest, *pieces]), cfg.checks), cfg).facades[1]
    [one] = _of(got, ElementClass.CORNICE)
    assert (one.x_m, one.w_m) == (0.0, f.side.length_m)
    assert one.y_m + one.h_m == pytest.approx(house.spec.eaves_m)
    assert one.h_m == pytest.approx(c.h_m)


def test_plinth_on_one_wall_goes_on_all(house, cfg):
    """Цоколь у модели — на одной стене и выше отметки цоколя; после шага 5 — на всех стенах от
    земли до `plinth_m`, а основная отделка — от его верха."""
    sheet = house
    for i, f in enumerate(house.facades):
        zones = [whole_main(f, house.spec.eaves_m)]
        if i == 1:  # единственный цоколь дома — выше отметки, основная отделка — от его верха
            main = zones[0]
            zones = [MaterialZone.rect(ZoneRole.PLINTH, PaletteRole.PLINTH,
                                       (0, 0, f.side.length_m, 0.8)),
                     MaterialZone.rect(ZoneRole.MAIN, main.material,
                                       (0, 0.8, f.side.length_m, house.spec.eaves_m))]
        sheet = with_side(sheet, i, zones=zones)
    got = _clean(snap(sheet, cfg.checks), cfg)
    for f in got.facades:
        [plinth] = _plinths(f)
        assert plinth.material == PaletteRole.PLINTH
        assert _top(plinth) == pytest.approx(house.spec.plinth_m)
        main = next(z for z in f.zones if z.role is ZoneRole.MAIN)
        assert min(y for _, y in main.shape) == pytest.approx(house.spec.plinth_m)


def test_no_plinth_without_plinth_height(house, cfg):
    """У дома без цоколя (`plinth_m` = 0) зон цоколя нет, даже если модель их поставила."""
    spec = house.spec.model_copy(update={"plinth_m": 0.0})
    got = _clean(snap(house.model_copy(update={"spec": spec}), cfg.checks), cfg)
    assert [z for f in got.facades for z in _plinths(f)] == []


def _canopy(door: Element) -> Element:
    return Element(id=f"k_{door.id}", cls=ElementClass.CANOPY, x_m=door.x_m - 0.2,
                   y_m=door.y_m + door.h_m + 0.1, w_m=door.w_m + 0.4, h_m=0.1, floor=1,
                   parent=door.id, material=PaletteRole.TRIM)


def _door_case(house, y: float, child) -> tuple:
    """Дверь стороны DOOR_SIDE на высоте y со своим ребёнком child(door)."""
    f = house.facades[DOOR_SIDE]
    door = _of(f, ElementClass.DOOR)[0].model_copy(update={"y_m": y})
    elements = [door if e.id == door.id else e for e in f.elements] + [child(door)]
    return with_side(house, DOOR_SIDE, elements=elements), door


def _on_floor(sheet, child: ElementClass, cfg) -> tuple[Element, Element]:
    """Дверь стороны DOOR_SIDE после шага 5 — на полу первого этажа; она и её ребёнок класса
    child."""
    got = _clean(snap(sheet, cfg.checks), cfg).facades[DOOR_SIDE]
    [d] = _of(got, ElementClass.DOOR)
    [c] = _of(got, child)
    assert d.y_m == pytest.approx(sheet.spec.plinth_m)
    return d, c


def test_door_in_the_air_lands_on_floor_with_canopy(house, cfg):
    """Дверь на 1,85 м — на пол первого этажа (`plinth_m`), той же высоты; козырёк над ней едет
    вместе с ней и стоит с тем же зазором."""
    sheet, door = _door_case(house, 1.85, _canopy)
    d, k = _on_floor(sheet, ElementClass.CANOPY, cfg)
    assert d.h_m == pytest.approx(door.h_m)
    assert k.y_m - (d.y_m + d.h_m) == pytest.approx(0.1)


def test_porch_reaches_door_raised_off_the_ground(house, cfg):
    """Дверь на земле при цоколе — на пол этажа; крыльцо — от земли до её низа."""
    def porch(door):
        return Element(id=f"p_{door.id}", cls=ElementClass.PORCH, x_m=door.x_m - 0.3, y_m=0.0,
                       w_m=door.w_m + 0.6, h_m=0.15, floor=1, parent=door.id,
                       material=PaletteRole.PLINTH)

    sheet, _ = _door_case(house, 0.0, porch)
    d, p = _on_floor(sheet, ElementClass.PORCH, cfg)
    assert (p.y_m, p.h_m) == (0.0, pytest.approx(d.y_m))


def test_garage_door_stays_on_ground(house, cfg):
    """Гаражные ворота стоят на земле — уровень пола их не двигает."""
    f = house.facades[DOOR_SIDE]
    door = _of(f, ElementClass.DOOR)[0]
    gate = door.model_copy(update={"cls": ElementClass.GARAGE_DOOR, "y_m": 0.0})
    elements = [gate if e.id == door.id else e for e in f.elements]
    sheet = with_side(house, DOOR_SIDE, elements=elements)
    [got] = _of(snap(sheet, cfg.checks).facades[DOOR_SIDE], ElementClass.GARAGE_DOOR)
    assert abs(got.y_m) < EPS


def _moved_window(house, side: int, **update):
    """Лист, где окно стороны side (с подоконником) сдвинуто: поля update у окна, подоконник —
    на столько же по высоте."""
    f = house.facades[side]
    w = _of(f, ElementClass.WINDOW)[0]
    moved = w.model_copy(update=update)
    dy = moved.y_m - w.y_m
    elements = [moved if e.id == w.id else
                e.model_copy(update={"y_m": e.y_m + dy}) if e.parent == w.id else e
                for e in f.elements]
    return with_side(house, side, elements=elements), w


def _window_of(sheet, side: int, cfg) -> tuple[Element, Element]:
    """Окно стороны side после шага 5 и его подоконник."""
    f = _clean(snap(sheet, cfg.checks), cfg).facades[side]
    [w] = _of(f, ElementClass.WINDOW)
    [s] = _of(f, ElementClass.SILL)
    return w, s


def test_window_off_the_floor_line_joins_it(house, cfg):
    """gf#275: окно, чей верх отскочил от общей линии этажа по дому на 0,5 м, — на линию, той же
    высоты; подоконник — за ним. Отскок меньше `window_jump_m` остаётся — у настоящих домов верх
    окон этажа на разных стенах расходится на сантиметры."""
    sheet, w = _moved_window(house, 1, y_m=house.facades[1].elements[0].y_m + 0.5)
    got, sill = _window_of(sheet, 1, cfg)
    assert got.y_m + got.h_m == pytest.approx(w.y_m + w.h_m)
    assert got.h_m == pytest.approx(w.h_m)
    assert sill.y_m + sill.h_m == pytest.approx(got.y_m)
    small = cfg.checks.window_jump_m / 2
    sheet, w = _moved_window(house, 1, y_m=w.y_m + small)
    got, _ = _window_of(sheet, 1, cfg)
    assert got.y_m == pytest.approx(w.y_m + small)


def test_window_in_plinth_rises_above_it(house, cfg):
    """Окно, заходящее в цоколь (низ 0,2 м при цоколе 0,5 м), а верхом — у линии этажа, — низом на
    пол этажа той же высоты."""
    w = _of(house.facades[2], ElementClass.WINDOW)[0]
    sheet, _ = _moved_window(house, 2, y_m=0.2, h_m=w.y_m + w.h_m - 0.2 - 0.1)
    got, sill = _window_of(sheet, 2, cfg)
    assert got.y_m == pytest.approx(house.spec.plinth_m)
    assert got.h_m == pytest.approx(w.y_m + w.h_m - 0.3)
    assert sill.y_m + sill.h_m == pytest.approx(got.y_m)


def test_window_to_the_floor_keeps_its_top(house, cfg):
    """Окно в пол линии верха не держит: его верх на 0,5 м выше линии остаётся."""
    f = house.facades[1]
    w = _of(f, ElementClass.WINDOW)[0]
    panoramic = OpeningVariant(kind=VariantKind.PANORAMIC)
    tall = w.model_copy(update={"y_m": house.spec.plinth_m, "h_m": w.y_m + w.h_m + 0.5
                                - house.spec.plinth_m, "variant": panoramic})
    elements = [tall if e.id == w.id else e for e in f.elements if e.parent != w.id]
    got = snap(with_side(house, 1, elements=elements), cfg.checks).facades[1]
    [kept] = _of(got, ElementClass.WINDOW)
    assert (kept.y_m, kept.h_m) == (pytest.approx(tall.y_m), pytest.approx(tall.h_m))


def test_window_stays_if_its_line_is_taken(house, cfg):
    """Окно, которое на линии налезло бы на другой проём, остаётся где было."""
    f = house.facades[DOOR_SIDE]
    w = _of(f, ElementClass.WINDOW)[0]
    low = w.model_copy(update={"y_m": w.y_m - 1.0})
    door = _of(f, ElementClass.DOOR)[0]
    blocker = door.model_copy(update={"id": "d9", "x_m": w.x_m, "y_m": w.y_m + w.h_m - 0.6,
                                      "w_m": w.w_m, "h_m": 0.5, "fixed": []})
    elements = [low if e.id == w.id else e for e in f.elements if e.parent != w.id] + [blocker]
    got = snap(with_side(house, DOOR_SIDE, elements=elements), cfg.checks).facades[DOOR_SIDE]
    [kept] = [e for e in got.elements if e.id == w.id]
    assert kept.y_m == pytest.approx(low.y_m)


# gf#276: крыльцо у двери на поднятом полу — кодом шага 5
# (`facade: Крыльцо у двери на поднятом полу`).

def _raised(house, plinth_m: float):
    """Дом с полом, поднятым на plinth_m, и дверью стороны DOOR_SIDE, уже стоящей на нём."""
    spec = house.spec.model_copy(update={"plinth_m": plinth_m})
    sheet = house.model_copy(update={"spec": spec})
    door = _of(sheet.facades[DOOR_SIDE], ElementClass.DOOR)[0].model_copy(update={"y_m": plinth_m})
    return with_side(sheet, DOOR_SIDE, elements=[door if e.cls is ElementClass.DOOR else e
                                                 for e in sheet.facades[DOOR_SIDE].elements])


def _porches(sheet, cfg):
    return _of(_clean(snap(sheet, cfg.checks), cfg).facades[DOOR_SIDE], ElementClass.PORCH)


def test_raised_door_gets_porch_from_ground(house, cfg):
    """Дверь на 0,61 м без крыльца: крыльцо от земли до низа двери, шире двери на запас из
    настроек, у двери, материал — цоколь дома."""
    sheet = _raised(house, 0.61)
    [door] = _of(sheet.facades[DOOR_SIDE], ElementClass.DOOR)
    [p] = _porches(sheet, cfg)
    pad = cfg.checks.porch_pad_m
    assert (p.y_m, p.h_m) == (0.0, pytest.approx(0.61))
    assert (p.x_m, p.w_m) == (pytest.approx(door.x_m - pad), pytest.approx(door.w_m + 2 * pad))
    assert (p.parent, p.floor, p.material) == (door.id, 1, PaletteRole.PLINTH)


@pytest.mark.parametrize("plinth_m", [0.0, 0.15])
def test_door_on_the_ground_has_no_porch(house, cfg, plinth_m):
    """Дверь на земле и дверь на пороге `porch_min_m` (не выше него) — без крыльца."""
    assert plinth_m <= cfg.checks.porch_min_m
    assert _porches(_raised(house, plinth_m), cfg) == []


@pytest.mark.parametrize("parent", [None, "e9", "door"])
def test_model_porch_is_not_duplicated(house, cfg, parent):
    """Крыльцо модели у двери — одно: остаётся с её x и шириной, а встаёт от земли до низа двери.
    Разбор ответа ставит `parent` то верный, то пустой, то чужой — крыльцо ищется по x."""
    sheet = _raised(house, 0.61)
    [door] = _of(sheet.facades[DOOR_SIDE], ElementClass.DOOR)
    mine = Element(id="e9", cls=ElementClass.PORCH, x_m=door.x_m - 0.5, y_m=0.0, w_m=door.w_m + 1.0,
                   h_m=0.35, floor=1, parent=door.id if parent == "door" else parent,
                   material=PaletteRole.PLINTH)
    f = sheet.facades[DOOR_SIDE]
    sheet = with_side(sheet, DOOR_SIDE, elements=[*f.elements, mine])
    [p] = _porches(sheet, cfg)
    assert (p.id, p.x_m, p.w_m) == (mine.id, mine.x_m, mine.w_m)
    assert (p.y_m, p.h_m) == (0.0, pytest.approx(0.61))


def test_porch_stays_inside_the_wall(house, cfg):
    """Дверь у края стены: крыльцо обрезано краем, а не выходит за силуэт."""
    f = _raised(house, 0.61).facades[DOOR_SIDE]
    door = _of(f, ElementClass.DOOR)[0].model_copy(update={"x_m": 0.1, "fixed": []})
    sheet = with_side(_raised(house, 0.61), DOOR_SIDE,
                      elements=[door if e.cls is ElementClass.DOOR else e for e in f.elements])
    checks = cfg.checks.model_copy(update={"corner_min_m": 0.0})  # дверь остаётся у края (gf#313)
    got = snap(sheet, checks)
    [p] = _of(got.facades[DOOR_SIDE], ElementClass.PORCH)
    assert (p.x_m, p.x_m + p.w_m) == (0.0, pytest.approx(0.1 + door.w_m + cfg.checks.porch_pad_m))
    assert [v for v in validate(got, checks) if v.rule is Rule.OUTSIDE] == []


def test_upper_floor_door_has_no_porch(house, cfg):
    """Крыльцо — у двери первого этажа: у двери второго этажа его нет, как бы высоко она ни
    стояла."""
    sheet = _raised(house, 0.61)
    f = sheet.facades[DOOR_SIDE]
    door = _of(f, ElementClass.DOOR)[0]
    spec = sheet.spec.model_copy(update={"floors": 2, "floor_heights_m": [2.75, 2.75],
                                         "eaves_m": 6.11})
    upper = door.model_copy(update={"id": "up", "floor": 2, "x_m": door.x_m + 3.0, "y_m": 3.36,
                                    "fixed": []})
    sheet = with_side(sheet.model_copy(update={"spec": spec}), DOOR_SIDE,
                      elements=[*f.elements, upper])
    got = snap(sheet, cfg.checks).facades[DOOR_SIDE]
    assert [p.parent for p in _of(got, ElementClass.PORCH)] == [door.id]


@pytest.mark.parametrize(("palette_has_plinth", "material"),
                         [(True, PaletteRole.PLINTH), (False, None)])
def test_porch_material_without_plinth_zones(house, cfg, palette_has_plinth, material):
    """Модель цоколя не поставила: материал крыльца — роль «цоколь» палитры, а нет и её —
    материала нет, цвет по классу (в палитре дома только то, что в ней есть)."""
    sheet = _raised(house, 0.61)
    for i, f in enumerate(sheet.facades):
        sheet = with_side(sheet, i, zones=[whole_main(f, sheet.spec.eaves_m)])
    palette = [m for m in sheet.spec.materials if palette_has_plinth or m.id != PaletteRole.PLINTH]
    sheet = sheet.model_copy(update={"spec": sheet.spec.model_copy(update={"materials": palette})})
    [p] = _porches(sheet, cfg)
    assert p.material == material


@pytest.mark.parametrize(("kind", "with_cornice"), [
    (RoofKind.GABLE, {"long"}), (RoofKind.HIP, {"long", "short"}),
    (RoofKind.FLAT, {"long", "short"})])
def test_cornice_only_under_the_slope(house, cfg, kind, with_cornice):
    """`facade: Карниз под скатом`: у двускатной крыши карниз — только на длинных стенах, на
    щипцовых его нет; у вальмовой и плоской — на всех, где его поставила модель (gf#320)."""
    roof = cfg.models.spec.roof_shape.roof(kind, "roof")
    sheet = house.model_copy(update={"spec": house.spec.model_copy(update={"roof": roof})})
    assert all(_of(f, ElementClass.CORNICE) for f in sheet.facades)  # модель — на всех
    got = snap(sheet, cfg.checks)
    longest = max(f.side.length_m for f in got.facades)
    has = {"long" if f.side.length_m == longest else "short"
           for f in got.facades if _of(f, ElementClass.CORNICE)}
    assert has == with_cornice


# gf#313: двери и углы кодом шага 5 (`facade: Высота дверей этажа`, `facade: Ширина двери`,
# `facade: Проём не у угла`).

def _door_on(house, side: int, id_: str, **update) -> Element:
    """Новая дверь стороны side — копия двери входа, не заданная планом."""
    door = _of(house.facades[DOOR_SIDE], ElementClass.DOOR)[0]
    return door.model_copy(update={"id": id_, "fixed": [], **update})


def _with(house, side: int, *added: Element, drop: tuple[str, ...] = ()):
    """Лист, где у стороны side добавлены added и убраны элементы с id из drop и их дети."""
    elements = [e for e in house.facades[side].elements
                if e.id not in drop and e.parent not in drop] + list(added)
    return with_side(house, side, elements=elements)


def _only(f, cls: ElementClass, id_: str) -> Element:
    return next(e for e in _of(f, cls) if e.id == id_)


@pytest.mark.parametrize(("heights", "same"), [((2.0, 2.3), True), ((2.1, 2.2), False)])
def test_doors_of_a_floor_get_one_height(house, cfg, heights, same):
    """gf#313: двери первого этажа на разных стенах высотой 2,0 и 2,3 м — обе по медиане 2,15 м,
    низ на полу; разброс в пределах `door_spread_m` (у настоящих домов — сантиметры) остаётся."""
    low, high = heights
    base = _of(house.facades[DOOR_SIDE], ElementClass.DOOR)[0]
    sheet = _with(house, DOOR_SIDE, base.model_copy(update={"h_m": low}), drop=(base.id,))
    sheet = _with(sheet, 2, _door_on(house, 2, "d2", x_m=1.0, h_m=high))
    got = _clean(snap(sheet, cfg.checks), cfg)
    a, b = (_only(got.facades[side], ElementClass.DOOR, id_).h_m
            for side, id_ in ((0, "d1"), (2, "d2")))
    assert (a == pytest.approx(b)) is same
    assert (a, b) == (pytest.approx((low + high) / 2),) * 2 if same else (low, high)


def test_door_with_transom_is_not_a_height_jump(house, cfg):
    """Дверь с фрамугой выше двери без неё по замыслу — это не разброс высот этажа."""
    transom = OpeningVariant(kind=VariantKind.TRANSOM)
    sheet = _with(house, 2, _door_on(house, 2, "d2", x_m=1.0, h_m=2.6, variant=transom))
    got = snap(sheet, cfg.checks)
    assert _only(got.facades[2], ElementClass.DOOR, "d2").h_m == pytest.approx(2.6)
    assert _only(got.facades[0], ElementClass.DOOR, "d1").h_m == pytest.approx(2.1)


def test_narrow_door_is_widened_around_its_middle(house, cfg):
    """gf#313: дверь шириной 0,5 м — не уже `door_min_w_m`, середина та же."""
    sheet = _with(house, 2, _door_on(house, 2, "d2", x_m=1.0, w_m=0.5))
    d = _only(_clean(snap(sheet, cfg.checks), cfg).facades[2], ElementClass.DOOR, "d2")
    assert d.w_m == pytest.approx(cfg.checks.door_min_w_m)
    assert d.x_m + d.w_m / 2 == pytest.approx(1.25)


def test_narrow_door_stays_if_there_is_no_room(house, cfg):
    """Расширенная дверь налезла бы на окно по обе стороны от середины и вправо, влево — за
    стену: дверь остаётся узкой."""
    w = _of(house.facades[2], ElementClass.WINDOW)[0]
    left = w.model_copy(update={"id": "w9", "x_m": 0.5, "w_m": 0.4, "fixed": []})  # 0,5..0,9
    right = w.model_copy(update={"id": "w8", "x_m": 1.65, "w_m": 0.4, "fixed": []})  # 1,65..2,05
    narrow = _door_on(house, 2, "d2", x_m=1.0, w_m=0.6)  # 1,0..1,6: 0,8 м не влезает
    got = levels(_with(house, 2, left, right, narrow), cfg.checks).facades[2]
    assert _only(got, ElementClass.DOOR, "d2").w_m == pytest.approx(0.6)


def _window_at(house, x: float, **update) -> Element:
    """Окно стороны 2 (2,0 м шириной) на x от левого угла, не заданное планом."""
    w = _of(house.facades[2], ElementClass.WINDOW)[0]
    return w.model_copy(update={"x_m": x, "fixed": [], **update})


def _slid(house, x: float):
    """Лист, где окно стороны 2 вместе с подоконником стоит на x от левого угла."""
    w = _window_at(house, x)
    sill = next(e for e in _of(house.facades[2], ElementClass.SILL) if e.parent == w.id)
    return _with(house, 2, w, sill.model_copy(update={"x_m": sill.x_m + x - 3.0}),
                 drop=(w.id, sill.id))


def test_window_near_the_corner_moves_off_it(house, cfg):
    """gf#313: окно в 0,1 м от угла — на `corner_min_m` от него; подоконник за окном."""
    f = levels(_slid(house, 0.1), cfg.checks).facades[2]
    [w], [s] = _of(f, ElementClass.WINDOW), _of(f, ElementClass.SILL)
    assert w.x_m == pytest.approx(cfg.checks.corner_min_m)
    assert s.x_m + s.w_m / 2 == pytest.approx(w.x_m + w.w_m / 2)


def test_window_near_the_right_corner_moves_off_it(house, cfg):
    """То же у правого угла: отступ считается от ближнего угла."""
    wall = house.facades[2].side.length_m
    [w] = _of(levels(_slid(house, wall - 2.0 - 0.1), cfg.checks).facades[2], ElementClass.WINDOW)
    assert wall - w.x_m - w.w_m == pytest.approx(cfg.checks.corner_min_m)


def test_plan_opening_near_the_corner_is_not_touched(house, cfg):
    """Проём плана (`fixed`) не трогается: ни окно у угла, ни узкая дверь."""
    near = _window_at(house, 0.1, fixed=[FixedField.X, FixedField.W])
    narrow = _door_on(house, 2, "d2", x_m=6.0, w_m=0.5, fixed=[FixedField.X, FixedField.W])
    got = levels(_with(house, 2, near, narrow, drop=("w1_1",)), cfg.checks).facades[2]
    assert (_only(got, ElementClass.WINDOW, "w1_1").x_m,
            _only(got, ElementClass.DOOR, "d2").w_m) == (0.1, 0.5)


def test_shift_onto_a_neighbour_is_not_made(house, cfg):
    """Окно в 0,1 м от угла, а справа вплотную — окно плана: сдвиг налез бы на него, окно
    остаётся."""
    near = _window_at(house, 0.1, w_m=1.0)
    wall = _window_at(house, 1.15, w_m=1.0, id="w2", fixed=[FixedField.X, FixedField.W])
    got = levels(_with(house, 2, near, wall, drop=("w1_1",)), cfg.checks).facades[2]
    assert _only(got, ElementClass.WINDOW, "w1_1").x_m == pytest.approx(0.1)


def test_shift_pushes_a_free_neighbour_with_its_gap(house, cfg):
    """Сосед не из плана уезжает перед сдвинутым окном с прежним зазором — без наложения."""
    near = _window_at(house, 0.1, w_m=1.0)
    other = _window_at(house, 1.35, w_m=1.0, id="w2")  # зазор 0,25 м
    got = levels(_with(house, 2, near, other, drop=("w1_1",)), cfg.checks).facades[2]
    a, b = (_only(got, ElementClass.WINDOW, i) for i in ("w1_1", "w2"))
    assert a.x_m == pytest.approx(cfg.checks.corner_min_m)
    assert b.x_m - (a.x_m + a.w_m) == pytest.approx(0.25)


def test_shift_without_room_in_the_wall_is_not_made(house, cfg):
    """Стена 5 м: два окна по 2,3 м не дают отступа от обоих углов — всё остаётся."""
    f = house.facades[1]
    w = _of(f, ElementClass.WINDOW)[0]
    a = w.model_copy(update={"x_m": 0.1, "w_m": 2.3, "fixed": []})
    b = w.model_copy(update={"id": "w2", "x_m": 2.5, "w_m": 2.3, "fixed": []})
    got = levels(_with(house, 1, a, b, drop=("w1_1",)), cfg.checks).facades[1]
    assert [e.x_m for e in _of(got, ElementClass.WINDOW)] == [0.1, 2.5]


def test_porch_follows_the_door_moved_off_the_corner(house, cfg):
    """Дверь отъехала от угла — крыльцо модели с ней (по x), второго крыльца не ставится."""
    sheet = _raised(house, 0.61)
    door = _door_on(house, DOOR_SIDE, "d3", x_m=0.1, y_m=0.61)
    porch = Element(id="p3", cls=ElementClass.PORCH, x_m=0.0, y_m=0.0, w_m=door.w_m + 0.2,
                    h_m=0.61, floor=1, parent=door.id, material=PaletteRole.PLINTH)
    got = levels(_with(sheet, DOOR_SIDE, door, porch, drop=("d1",)), cfg.checks).facades[DOOR_SIDE]
    [d], [p] = _of(got, ElementClass.DOOR), _of(got, ElementClass.PORCH)
    assert d.x_m == pytest.approx(cfg.checks.corner_min_m)
    assert p.x_m == pytest.approx(d.x_m - 0.1)


@pytest.mark.parametrize("kind", [VariantKind.CORNER, VariantKind.STRIP])
def test_corner_window_stays_at_the_corner(house, cfg, kind):
    """Угловое и ленточное окно стоит у угла по замыслу — отступа от него у них нет."""
    sheet = _with(house, 2, _window_at(house, 0.0, variant=OpeningVariant(kind=kind)),
                  drop=("w1_1",))
    [w] = _of(levels(sheet, cfg.checks).facades[2], ElementClass.WINDOW)
    assert w.x_m == 0.0
