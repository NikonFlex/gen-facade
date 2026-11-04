"""Карниз, цоколь и низ двери — по параметрам дома (gf#272, `facade: Высоты цоколя и карниза — из
параметров`, `facade: Нуль отметок — земля`): шаг 5 ставит их на отметки дома, что бы ни
ответила модель шага 4. Дом — простой из conftest: цоколь 0,5 м, карниз 3,25 м, дверь на стороне 0.
"""

import pytest
from simple_house import whole_main, with_side

from genfacade.schema import EPS, Element, ElementClass, MaterialZone, PaletteRole, ZoneRole
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
    """У стаба шага 4 всё уже на отметках дома — шаг 5 ничего не трогает."""
    assert snap(house, cfg.checks) == house


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
