"""Правило шага 4 на простом доме: проёмы, декор, зоны (generation.md, facade.md правило 9).

Дом из config/house.json — один этаж, плоская крыша, стиль modern. Что правило умеет сверх
него (этажи, наличники, уровни окон), проверяется правкой параметров того же дома (relayout).
"""

import pytest

from genfacade.schema import EPS, FacadeSheet


def _of(sheet, cls):
    return [e for f in sheet.facades for e in f.elements if e.cls == cls]


def _level(cfg, level):
    windows = cfg.layout.windows.model_copy(update={"level": level})
    return cfg.layout.model_copy(update={"windows": windows})


def test_simple_house_layout(lay_out):
    """Один этаж: окна и дверь из плана, у каждого окна подоконник, карниз на каждой стене."""
    sheet = lay_out()
    assert len(_of(sheet, "window")) == 4 and len(_of(sheet, "door")) == 1
    assert {s.parent for s in _of(sheet, "sill")} == {w.id for w in _of(sheet, "window")}
    assert len(_of(sheet, "cornice")) == 4
    assert _of(sheet, "molding") == []  # у стиля modern наличников нет


def test_plan_fields_fixed_only_where_plan_sets_them(lay_out, relayout, two_floors):
    sheet = relayout(lay_out(), **two_floors)
    windows = _of(sheet, "window")
    assert all(w.fixed == ["x_m", "w_m"] for w in windows if w.floor == 1)
    assert all(w.fixed == [] for w in windows if w.floor > 1)
    assert all(d.fixed == ["x_m", "w_m"] for d in _of(sheet, "door"))


def test_windows_stacked_on_every_floor(lay_out, relayout, cfg, two_floors):
    """Окна первого этажа повторяются выше; над дверью на втором — ещё окно, если влезает."""
    sheet = relayout(lay_out(), **two_floors)
    for f in sheet.facades:
        cols = {n: {(w.x_m, w.w_m) for w in f.elements if w.cls == "window" and w.floor == n}
                for n in (1, 2)}
        assert cols[1] <= cols[2]
    door_side = next(f for f in sheet.facades if f.side.has_entrance)
    upper = [w for w in door_side.elements if w.cls == "window" and w.floor == 2]
    door = next(e for e in door_side.elements if e.cls == "door")
    axis = door.x_m + door.w_m / 2
    assert any(abs(w.x_m + w.w_m / 2 - axis) < EPS and w.w_m == cfg.layout.blind.widths_m[0]
               for w in upper)


@pytest.mark.parametrize("level", ["small", "standard", "high"])
@pytest.mark.parametrize("mode", ["with_openings", "blind"])
def test_windows_between_floor_and_lintel(lay_out, relayout, cfg, level, mode, two_floors):
    sheet = relayout(lay_out(mode), mode, _level(cfg, level), **two_floors)
    levels = sheet.spec.floor_levels()
    assert _of(sheet, "window")
    for w in _of(sheet, "window"):
        assert w.y_m >= levels[w.floor - 1] - EPS
        assert w.y_m + w.h_m <= levels[w.floor] - cfg.layout.windows.lintel_m + EPS


@pytest.mark.parametrize("level", ["small", "standard", "high"])
def test_window_height_level_from_config(lay_out, relayout, cfg, level):
    sheet = relayout(lay_out(), rule=_level(cfg, level))
    low, _ = cfg.layout.windows.size[level]
    base, fh = sheet.spec.plinth_m, sheet.spec.floor_heights_m[0]
    assert all(w.y_m == pytest.approx(base + low * fh) for w in _of(sheet, "window"))
    panoramic = [w for w in _of(sheet, "window") if w.variant.kind == "panoramic"]
    assert bool(panoramic) == (level == "high")
    assert (_of(sheet, "sill") == []) == (level == "high")  # у окна в пол подоконника нет


def test_casings_by_style_drawn_under_window(lay_out, relayout):
    classic = relayout(lay_out(), style="classic")
    assert {m.parent for m in _of(classic, "molding")} == {w.id for w in _of(classic, "window")}
    for f in classic.facades:
        order = [e.id for e in f.elements]
        for m in (e for e in f.elements if e.cls == "molding"):
            assert order.index(m.id) < order.index(m.parent)


def test_zone_heights_same_on_all_sides(lay_out, relayout, two_floors):
    """Цоколь, основная отделка и пояса — по отметкам HouseSpec: углы сходятся."""
    for sheet in (lay_out(), relayout(lay_out(), **two_floors)):
        bands = [{(round(min(y for _, y in z.shape), 6), round(max(y for _, y in z.shape), 6))
                  for z in f.zones if z.role in ("plinth", "main", "band")} for f in sheet.facades]
        assert all(b == bands[0] for b in bands)
        belts = [z for z in sheet.facades[0].zones if z.role == "band"]
        assert len(belts) == sheet.spec.floors - 1


def test_accent_at_entrance_or_gable(lay_out):
    flat = lay_out()
    with_accent = [f.side.index for f in flat.facades if any(z.role == "accent" for z in f.zones)]
    assert with_accent == [0]  # плоская крыша: полоса у входа
    gable = lay_out(roof="gable")
    for f in gable.facades:
        accents = [z for z in f.zones if z.role == "accent"]
        if len(f.silhouette) == 5:  # фронтон — акцент в нём, выше карниза
            assert accents and min(y for _, y in accents[0].shape) >= gable.spec.eaves_m - EPS
        else:  # без фронтона — полоса только у входа
            assert bool(accents) == f.side.has_entrance


def test_blind_windows_on_every_side(lay_out, cfg):
    """Глухой режим: окна на каждой стороне; основная ширина, где влезает (справа от двери —
    1 м до угла, там запасная)."""
    sheet = lay_out("blind")
    widths = [round(w.w_m, 6) for w in _of(sheet, "window")]
    assert all(any(e.cls == "window" for e in f.elements) for f in sheet.facades)
    main, allowed = cfg.layout.blind.widths_m[0], set(cfg.layout.blind.widths_m)
    assert widths.count(main) >= 4 and set(widths) <= allowed


def test_blind_spare_width_between_zones(lay_out, simple_svg, cfg):
    """Внутренние стены режут левую стену: основная ширина не влезает, там — запасная."""
    leaf = '<rect x="800" y="495" width="5" height="90" fill="#000000" />'
    inner = ('<rect x="115" y="250" width="285" height="10" fill="#000000" />'
             '<rect x="115" y="390" width="285" height="10" fill="#000000" />')
    sheet = lay_out("blind", svg=simple_svg((leaf, inner + leaf)))
    assert {round(w.w_m, 6) for w in _of(sheet, "window")} == set(cfg.layout.blind.widths_m)


def test_palette_not_by_roles(lay_out, relayout):
    """Палитра, написанная руками без ролей: роли по порядку, материал крыши — не на стены."""
    sheet = lay_out()
    # материал крыши — первым: без исключения он стал бы основной отделкой стен
    materials = sheet.spec.materials[-1:] + sheet.spec.materials[:-1]
    renamed = [m.model_copy(update={"id": f"m{i}"}) for i, m in enumerate(materials)]
    roof = sheet.spec.roof.model_copy(update={"material": "m0"})
    laid = relayout(sheet, materials=renamed, roof=roof)
    FacadeSheet.model_validate(laid.model_dump())  # все ссылки — в палитру
    used = {z.material for f in laid.facades for z in f.zones}
    used |= {e.material for f in laid.facades for e in f.elements if e.material}
    assert "m0" not in used and used <= {"m1", "m2", "m3", "m4"}


def test_blind_window_not_on_entrance_accent(lay_out):
    """Полоса акцента у входа — на ширину зазора, куда окна не ставятся: окна на неё не заходят."""
    side = lay_out("blind").facades[0]
    accent = next(z for z in side.zones if z.role == "accent")
    x0, x1 = min(x for x, _ in accent.shape), max(x for x, _ in accent.shape)
    for w in (e for e in side.elements if e.cls == "window" and e.floor == 1):
        assert w.x_m + w.w_m <= x0 + EPS or w.x_m >= x1 - EPS, w.id
