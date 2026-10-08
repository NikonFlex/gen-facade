"""Валидатор и привязка к сетке (evaluation.md правило 1, generation.md п. 7; gf#15).

На каждое правило — испорченный пример, на котором оно срабатывает, и чистый, на котором молчит.
Критерий «молчит на эталонной разметке CMP» — этап 2 (gf#12).
"""

import pytest
from simple_house import WALL_INTO_WINDOW, before_leaf

from genfacade.render.svg import sheet_svg
from genfacade.schema import ElementClass, Rule
from genfacade.snap import snap
from genfacade.unfold import unfold
from genfacade.validate import errors, validate, validate_svg


@pytest.fixture
def clean(lay_out):
    """Лист без нарушений: простой дом в два этажа (стены 6 м) с окном второго этажа над окном
    первого на стороне SIDE — чтобы было окно над окном для проверок осей и привязки."""
    return _with_upper(lay_out())


def _with_upper(sheet):
    """Тот же дом в два этажа; на стороне SIDE — окно второго этажа с подоконником."""
    spec = sheet.spec.model_copy(update={"floors": 2, "floor_heights_m": [2.75, 2.75],
                                          "eaves_m": 6.0})
    sheet = unfold(sheet.model_copy(update={"spec": spec}))
    f = sheet.facades[SIDE]
    low = next(e for e in f.elements if e.cls is ElementClass.WINDOW)
    sill = next(e for e in f.elements if e.parent == low.id)
    up = spec.floor_heights_m[0]
    upper = low.model_copy(update={"id": "upper", "floor": 2, "y_m": low.y_m + up, "fixed": []})
    upper_sill = sill.model_copy(update={"id": "s_upper", "parent": "upper", "floor": 2,
                                         "y_m": sill.y_m + up})
    facades = list(sheet.facades)
    facades[SIDE] = f.model_copy(update={"elements": [*f.elements, upper, upper_sill]})
    return sheet.model_copy(update={"facades": facades})


def _edit(sheet, side, element_id, **update):
    f = sheet.facades[side]
    elements = [e.model_copy(update=update) if e.id == element_id else e for e in f.elements]
    facades = list(sheet.facades)
    facades[side] = f.model_copy(update={"elements": elements})
    return sheet.model_copy(update={"facades": facades})


SIDE = 1  # левая сторона простого дома: без входа


def _window(sheet, side=SIDE, floor=1):
    return next(e for e in sheet.facades[side].elements
                if e.cls is ElementClass.WINDOW and e.floor == floor)


def _rules(sheet, cfg):
    return {v.rule for v in validate(sheet, cfg.checks)}


def test_clean_sheet_has_no_violations(clean, cfg, house):
    assert validate(clean, cfg.checks) == []
    assert validate(house, cfg.checks) == []  # простой дом как есть, режим 2


def test_outside_silhouette(clean, cfg):
    w = _window(clean)
    assert Rule.OUTSIDE in _rules(_edit(clean, SIDE, w.id, x_m=-0.5), cfg)


def test_openings_overlap(clean, cfg):
    a, b = _window(clean, floor=1), _window(clean, floor=2)
    assert Rule.OVERLAP in _rules(_edit(clean, SIDE, b.id, y_m=a.y_m + 0.1), cfg)


def test_window_in_forbidden_zone(lay_out, simple_svg, cfg):
    # режим 2: окно плана стоит там, куда упирается внутренняя стена
    found = validate(lay_out(svg=simple_svg(before_leaf(WALL_INTO_WINDOW))), cfg.checks)
    assert {(v.rule, v.side) for v in found} == {(Rule.FORBIDDEN, 2)}


def test_plan_opening_moved(lay_out, cfg):
    sheet = lay_out()
    door = next(e for e in sheet.facades[0].elements if e.cls is ElementClass.DOOR)
    assert Rule.PLAN_OPENING in _rules(_edit(sheet, 0, door.id, x_m=door.x_m + 0.3), cfg)


def test_corner_heights(clean, cfg):
    f = clean.facades[1]
    lowered = [(x, y - 0.3 if x == 0 else y) for x, y in f.silhouette]
    facades = list(clean.facades)
    facades[1] = f.model_copy(update={"silhouette": lowered})
    assert Rule.CORNER in _rules(clean.model_copy(update={"facades": facades}), cfg)


def _with_neighbour(sheet, w, dy: float):
    """Второе окно на этаже того же размера, правее и выше на dy."""
    f = sheet.facades[SIDE]
    twin = w.model_copy(update={"id": "twin", "x_m": w.x_m + w.w_m + 0.2, "y_m": w.y_m + dy})
    facades = list(sheet.facades)
    facades[SIDE] = f.model_copy(update={"elements": [*f.elements, twin]})
    return sheet.model_copy(update={"facades": facades})


def test_floor_align_warning(clean, cfg):
    found = validate(_with_neighbour(clean, _window(clean), dy=0.1), cfg.checks)
    assert Rule.FLOOR_ALIGN in {v.rule for v in found} and errors(found) == []


def test_lower_sill_with_same_top_is_not_misaligned(clean, cfg):
    """Окно в пол рядом с обычным: верх общий, низ разный — так задумано, предупреждения нет."""
    w = _window(clean)
    sheet = _with_neighbour(clean, w, dy=0.0)
    lower = _edit(sheet, SIDE, "twin", y_m=w.y_m - 0.4, h_m=w.h_m + 0.4)
    assert Rule.FLOOR_ALIGN not in _rules(lower, cfg)


def test_axis_align_warning(clean, cfg):
    w = _window(clean, floor=2)
    found = validate(_edit(clean, SIDE, w.id, x_m=w.x_m + 0.03), cfg.checks)
    assert Rule.AXIS_ALIGN in {v.rule for v in found} and errors(found) == []


def test_svg_checked_like_json(clean, cfg):
    bad = _edit(clean, SIDE, _window(clean).id, x_m=-0.5)
    assert Rule.OUTSIDE in {v.rule for v in validate_svg(sheet_svg(bad, cfg), clean, cfg.checks)}
    assert validate_svg(sheet_svg(clean, cfg), clean, cfg.checks) == []
    assert [v.rule for v in validate_svg("<svg", clean, cfg.checks)] == [Rule.SVG_PARSE]


def test_snap_aligns_jittered_windows(clean, cfg):
    upper = _window(clean, floor=2)
    jittered = _edit(clean, SIDE, upper.id, x_m=upper.x_m + 0.08)
    snapped = snap(jittered, cfg.checks)
    assert Rule.AXIS_ALIGN not in _rules(snapped, cfg)
    moved, low = _window(snapped, floor=2), _window(snapped, floor=1)
    assert moved.x_m == pytest.approx(low.x_m)  # оба — на средней оси
    before = _sill(jittered, upper.id).x_m - (upper.x_m + 0.08)
    # подоконник едет вместе с окном
    assert _sill(snapped, moved.id).x_m - moved.x_m == pytest.approx(before)


def _sill(sheet, window_id):
    return next(e for e in sheet.facades[SIDE].elements
                if e.parent == window_id and e.cls is ElementClass.SILL)


def test_snap_keeps_plan_windows(lay_out, cfg):
    sheet = _with_upper(lay_out())
    w = _window(sheet, floor=2)
    snapped = snap(_edit(sheet, SIDE, w.id, x_m=w.x_m + 0.1), cfg.checks)
    plan_w = _window(snapped, floor=1)
    assert plan_w == _window(sheet, floor=1)  # заданное планом не сдвинулось
    assert _window(snapped, floor=2).x_m == pytest.approx(plan_w.x_m)


def test_snap_centers_model_windows_on_common_axis(clean, cfg):
    """Режим 1: окна ставит модель (без `fixed`) — ось группы — медиана центров, а не левых краёв.

    Окна разной ширины со смещёнными осями встают на общую ось по центру и общую ширину.
    """
    low = _window(clean, floor=1)
    center = low.x_m + low.w_m / 2
    narrow = low.w_m - 0.2
    sheet = _edit(clean, SIDE, low.id, fixed=[])
    sheet = _edit(sheet, SIDE, "upper", w_m=narrow, x_m=center + 0.1 - narrow / 2)
    snapped = snap(sheet, cfg.checks)
    width = (low.w_m + narrow) / 2                   # медиана двух ширин
    for w in (_window(snapped, floor=1), _window(snapped, floor=2)):
        assert w.w_m == pytest.approx(width)
        assert w.x_m + w.w_m / 2 == pytest.approx(center + 0.05)  # медиана двух центров


def test_snap_leaves_clean_sheet_alone(clean, cfg):
    assert snap(clean, cfg.checks) == clean
