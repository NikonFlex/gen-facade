"""Валидатор и привязка к сетке (evaluation.md правило 1, generation.md п. 7; gf#15).

На каждое правило — испорченный пример, на котором оно срабатывает, и чистый, на котором молчит.
Критерий «молчит на эталонной разметке CMP» — этап 2 (gf#12).
"""

import pytest

from genfacade.render.svg import sheet_svg
from genfacade.snap import snap
from genfacade.validate import errors, validate, validate_svg

LEAF = '<rect x="800" y="495" width="5" height="90" fill="#000000" />'


@pytest.fixture
def clean(lay_out, relayout, two_floors):
    """Лист без нарушений: простой дом в режиме 1, два этажа — чтобы были окна над окнами."""
    return relayout(lay_out("blind"), "blind", **two_floors)


def _edit(sheet, side, element_id, **update):
    f = sheet.facades[side]
    elements = [e.model_copy(update=update) if e.id == element_id else e for e in f.elements]
    facades = list(sheet.facades)
    facades[side] = f.model_copy(update={"elements": elements})
    return sheet.model_copy(update={"facades": facades})


SIDE = 1  # левая сторона простого дома: без входа, окна на обоих этажах


def _window(sheet, side=SIDE, floor=1):
    return next(e for e in sheet.facades[side].elements if e.cls == "window" and e.floor == floor)


def _rules(sheet, cfg):
    return {v.rule for v in validate(sheet, cfg.checks)}


def test_clean_sheet_has_no_violations(clean, cfg, house):
    assert validate(clean, cfg.checks) == []
    assert validate(house, cfg.checks) == []  # простой дом с каждой крышей, режим 2


def test_outside_silhouette(clean, cfg):
    w = _window(clean)
    assert "outside" in _rules(_edit(clean, SIDE, w.id, x_m=-0.5), cfg)


def test_openings_overlap(clean, cfg):
    a, b = _window(clean, floor=1), _window(clean, floor=2)
    assert "overlap" in _rules(_edit(clean, SIDE, b.id, y_m=a.y_m + 0.1), cfg)


def test_window_in_forbidden_zone(lay_out, simple_svg, cfg):
    # режим 2: внутренняя стена заходит в полосу верхнего окна плана (дефект GenPlan)
    wall = '<rect x="700" y="108" width="9" height="200" fill="#000000" />'
    found = validate(lay_out(svg=simple_svg((LEAF, wall + LEAF))), cfg.checks)
    assert {(v.rule, v.side) for v in found} == {("forbidden", 2)}


def test_plan_opening_moved(lay_out, cfg):
    sheet = lay_out()
    door = next(e for e in sheet.facades[0].elements if e.cls == "door")
    assert "plan_opening" in _rules(_edit(sheet, 0, door.id, x_m=door.x_m + 0.3), cfg)


def test_corner_heights(clean, cfg):
    f = clean.facades[1]
    lowered = [(x, y - 0.3 if x == 0 else y) for x, y in f.silhouette]
    facades = list(clean.facades)
    facades[1] = f.model_copy(update={"silhouette": lowered})
    assert "corner" in _rules(clean.model_copy(update={"facades": facades}), cfg)


def _with_neighbour(sheet, w, dy: float):
    """Второе окно на этаже того же размера, правее и выше на dy."""
    f = sheet.facades[SIDE]
    twin = w.model_copy(update={"id": "twin", "x_m": w.x_m + w.w_m + 0.2, "y_m": w.y_m + dy})
    facades = list(sheet.facades)
    facades[SIDE] = f.model_copy(update={"elements": [*f.elements, twin]})
    return sheet.model_copy(update={"facades": facades})


def test_floor_align_warning(clean, cfg):
    found = validate(_with_neighbour(clean, _window(clean), dy=0.1), cfg.checks)
    assert "floor_align" in {v.rule for v in found} and errors(found) == []


def test_axis_align_warning(clean, cfg):
    w = _window(clean, floor=2)
    found = validate(_edit(clean, SIDE, w.id, x_m=w.x_m + 0.03), cfg.checks)
    assert "axis_align" in {v.rule for v in found} and errors(found) == []


def test_svg_checked_like_json(clean, cfg):
    bad = _edit(clean, SIDE, _window(clean).id, x_m=-0.5)
    assert "outside" in {v.rule for v in validate_svg(sheet_svg(bad, cfg), clean, cfg.checks)}
    assert validate_svg(sheet_svg(clean, cfg), clean, cfg.checks) == []
    assert [v.rule for v in validate_svg("<svg", clean, cfg.checks)] == ["svg_parse"]


def test_snap_aligns_jittered_windows(clean, cfg):
    upper, lower = _window(clean, floor=2), _window(clean, floor=1)
    jittered = _edit(clean, SIDE, upper.id, x_m=upper.x_m + 0.08)
    snapped = snap(jittered, cfg.checks)
    assert "axis_align" not in _rules(snapped, cfg)
    moved, low = _window(snapped, floor=2), _window(snapped, floor=1)
    assert moved.x_m == pytest.approx(low.x_m)  # оба — на средней оси
    before = _sill(jittered, upper.id).x_m - (upper.x_m + 0.08)
    # подоконник едет вместе с окном
    assert _sill(snapped, moved.id).x_m - moved.x_m == pytest.approx(before)
    assert lower.floor == 1


def _sill(sheet, window_id):
    return next(e for e in sheet.facades[SIDE].elements
                if e.parent == window_id and e.cls == "sill")


def test_snap_keeps_plan_windows(lay_out, relayout, two_floors, cfg):
    sheet = relayout(lay_out(), **two_floors)
    w = _window(sheet, side=1, floor=2)
    snapped = snap(_edit(sheet, 1, w.id, x_m=w.x_m + 0.1), cfg.checks)
    plan_w = _window(snapped, side=1, floor=1)
    assert plan_w == _window(sheet, side=1, floor=1)  # заданное планом не сдвинулось
    assert _window(snapped, side=1, floor=2).x_m == pytest.approx(plan_w.x_m)


def test_snap_leaves_clean_sheet_alone(clean, cfg):
    assert snap(clean, cfg.checks) == clean
