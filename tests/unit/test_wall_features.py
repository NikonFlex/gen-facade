"""Признаки стены слоя «отличим ли от настоящего» (gf#243): каждый — с двух концов, на простом
доме и на том же доме с изъяном, который признак должен видеть."""

import pytest

from genfacade.metrics import wall_features
from genfacade.schema import ElementClass, FacadeSheet, MaterialZone, ZoneRole


def _values(sheet: FacadeSheet, cfg) -> dict[str, list[float]]:
    """Все признаки FEATURES: имя → значение на каждой стене."""
    settings = cfg.metrics.realism.model_copy(update={"features": list(wall_features.FEATURES)})
    rows = wall_features.of_house(sheet, settings)
    return {n: [r[i] for r in rows] for i, n in enumerate(settings.features)}


def _wall(sheet: FacadeSheet, i: int, **update) -> FacadeSheet:
    facades = list(sheet.facades)
    facades[i] = facades[i].model_copy(update=update)
    return sheet.model_copy(update={"facades": facades})


def _moved(sheet: FacadeSheet, i: int, cls: ElementClass, **update) -> FacadeSheet:
    """Элементы класса cls на стене i с полями update."""
    f = sheet.facades[i]
    return _wall(sheet, i, elements=[e.model_copy(update=update) if e.cls is cls else e
                                     for e in f.elements])


def _added(sheet: FacadeSheet, i: int, cls: ElementClass, **update) -> FacadeSheet:
    """Копия первого элемента класса cls на стене i с полями update."""
    f = sheet.facades[i]
    first = next(e for e in f.elements if e.cls is cls)
    extra = first.model_copy(update={"id": first.id + "x", **update})
    return _wall(sheet, i, elements=[*f.elements, extra])


def test_configured_features_are_known(cfg):
    assert set(cfg.metrics.realism.features) <= set(wall_features.FEATURES)


def test_bare_house_is_zero_but_blind(house, cfg):
    """Дом без элементов, одна основная зона на стене: глухие все стены и одна зона — остальные
    признаки ноль, как у идеально ровной стены."""
    bare = house
    for i, f in enumerate(house.facades):
        main = next(z for z in f.zones if z.role is ZoneRole.MAIN)
        whole = main.model_copy(update={"shape": [(0.0, 0.0), (f.side.length_m, 0.0),
                                                  (f.side.length_m, house.spec.eaves_m),
                                                  (0.0, house.spec.eaves_m)]})
        bare = _wall(bare, i, elements=[], zones=[whole])
    values = _values(bare, cfg)
    assert {n for n, v in values.items() if any(v)} == {"blind_walls", "zones"}
    assert values["blind_walls"] == [1.0] * 4


def test_corner_mismatch_sees_finish_cut_at_corner(house, cfg):
    assert _values(house, cfg)["corner_mismatch"][0] == 0.0
    f = house.facades[0]
    accent = MaterialZone(shape=[(0.0, 0.5), (1.0, 0.5), (1.0, 3.25), (0.0, 3.25)],
                          material="accent", role=ZoneRole.ACCENT)
    cut = _wall(house, 0, zones=[*f.zones, accent])
    assert _values(cut, cfg)["corner_mismatch"][0] > 0.0


def test_cornice_share_sees_short_cornice(house, cfg):
    assert _values(house, cfg)["cornice_share"][0] == 1.0
    short = _moved(house, 0, ElementClass.CORNICE, w_m=2.5)
    assert _values(short, cfg)["cornice_share"][0] == pytest.approx(0.25)


def test_hidden_zones_sees_accent_of_wall_material(house, cfg):
    assert _values(house, cfg)["hidden_zones"][0] == 0.0
    f = house.facades[0]
    hidden = [z.model_copy(update={"material": "main"}) if z.role is ZoneRole.ACCENT else z
              for z in f.zones]
    assert _values(_wall(house, 0, zones=hidden), cfg)["hidden_zones"][0] == 0.5


def test_sizes_floor_counts_window_sizes(house, cfg):
    same = _added(house, 0, ElementClass.WINDOW, x_m=3.5)
    other = _added(house, 0, ElementClass.WINDOW, x_m=3.5, w_m=0.6)
    assert _values(same, cfg)["sizes_floor"][0] == 1.0
    assert _values(other, cfg)["sizes_floor"][0] == 2.0


def test_symmetry_sees_mirror_twin(house, cfg):
    """Стена 2 (10 м): окно 3–5 м; двойник 5–7 м зеркален ему, 6–8 м — нет."""
    assert _values(house, cfg)["symmetry"][2] == 0.0
    assert _values(_added(house, 2, ElementClass.WINDOW, x_m=5.0), cfg)["symmetry"][2] == 1.0
    assert _values(_added(house, 2, ElementClass.WINDOW, x_m=6.0), cfg)["symmetry"][2] == 0.0


def test_min_pier_takes_narrowest_gap(house, cfg):
    """Стена 0: окно 1,5–2,7 м, дверь 7,0–7,9 м; окно у двери с простенком 0,3 м."""
    assert _values(house, cfg)["min_pier_m"][0] == pytest.approx(4.3)
    near = _added(house, 0, ElementClass.WINDOW, x_m=5.5)
    assert _values(near, cfg)["min_pier_m"][0] == pytest.approx(0.3)


def test_trim_mixed_sees_sills_at_some_windows(house, cfg):
    """Подоконник у каждого окна — 0; у половины окон — 1 по подоконникам, ставен нет — 0."""
    assert _values(house, cfg)["trim_mixed"][0] == 0.0
    f = house.facades[0]
    no_sill = [e for e in f.elements if e.cls is not ElementClass.SILL]
    half = _wall(_wall(house, 0, elements=no_sill), 2, elements=[
        e for e in house.facades[2].elements if e.cls is not ElementClass.SILL])
    assert _values(half, cfg)["trim_mixed"] == [0.5] * 4


def test_front_rich_compares_entrance_wall_with_back(house, cfg):
    """Стена входа 0 и тыльная 2 по 10 м: 2 проёма и 1 — 0,1 на метр; окно на тыльной — 0."""
    assert _values(house, cfg)["front_rich"][0] == pytest.approx(0.1)
    back = _added(house, 2, ElementClass.WINDOW, x_m=6.0)
    assert _values(back, cfg)["front_rich"] == [pytest.approx(0.0)] * 4
