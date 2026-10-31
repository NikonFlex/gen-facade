"""Валидатор и привязка к сетке
(`evaluation: Ошибки геометрии`, `generation: Привязка к сетке`; gf#15).

На каждое правило — испорченный пример, на котором оно срабатывает, и чистый, на котором молчит.
Критерий «молчит на эталонной разметке CMP» — этап 2 (gf#12).
"""

import pytest
from simple_house import WALL_INTO_WINDOW, before_leaf

from genfacade.render.svg import sheet_svg
from genfacade.schema import Element, ElementClass, MaterialZone, Rule, Severity, ZoneRole
from genfacade.snap import snap
from genfacade.unfold import unfold
from genfacade.validate import DEFECTS, defects, errors, validate, validate_svg


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
    facades = [_raised(g, sheet.spec.eaves_m) for g in sheet.facades]
    f = facades[SIDE]
    facades[SIDE] = f.model_copy(update={"elements": [*f.elements, upper, upper_sill]})
    return sheet.model_copy(update={"facades": facades})


def _raised(f, eaves: float):
    """Стена после подъёма карниза: зоны отделки — до нового карниза, карниз — под ним; иначе
    верх стены без отделки, а карниз — посреди второго этажа (gf#242)."""
    old = max(y for z in f.zones for _, y in z.shape)
    zones = [z.model_copy(update={"shape": [(x, eaves if y == old else y) for x, y in z.shape]})
             for z in f.zones]
    elements = [e.model_copy(update={"y_m": eaves - e.h_m}) if e.cls is ElementClass.CORNICE
                else e for e in f.elements]
    return f.model_copy(update={"zones": zones, "elements": elements})


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


def test_door_outside_the_wall(house, cfg):
    """Дверь за краем стены — брак (gf#242)."""
    door, length = _door(house), house.facades[FRONT].side.length_m
    assert Rule.OUTSIDE in _rules(_edit(house, FRONT, door.id, x_m=length - 0.4), cfg)


def test_openings_overlap(clean, cfg):
    a, b = _window(clean, floor=1), _window(clean, floor=2)
    assert Rule.OVERLAP in _rules(_edit(clean, SIDE, b.id, y_m=a.y_m + 0.1), cfg)


FRONT = 0  # сторона входа простого дома: дверь, окно, полоса акцента у двери


def _door(sheet):
    return next(e for e in sheet.facades[FRONT].elements if e.cls is ElementClass.DOOR)


def _added(sheet, side, *elements):
    f = sheet.facades[side]
    facades = list(sheet.facades)
    facades[side] = f.model_copy(update={"elements": [*f.elements, *elements]})
    return sheet.model_copy(update={"facades": facades})


def _zones(sheet, side, *zones):
    facades = list(sheet.facades)
    facades[side] = sheet.facades[side].model_copy(update={"zones": list(zones)})
    return sheet.model_copy(update={"facades": facades})


def _rect(role, x0, y0, x1, y1):
    return MaterialZone(role=role, material="main", shape=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_door_lower_than_the_norm(house, cfg):
    """Дверь ниже нормы свода `door_min_height` — брак (gf#242: у модели — 0,05 м); самая
    низкая дверь реального теста — 1,89 м — нет."""
    door = _door(house)
    assert Rule.DOOR_LOW in _rules(_edit(house, FRONT, door.id, h_m=0.1), cfg)
    assert Rule.DOOR_LOW not in _rules(_edit(house, FRONT, door.id, h_m=1.89), cfg)


def test_cornice_on_an_opening(house, cfg):
    """Карниз заходит на проём — брак (gf#242: карниз на двери и окнах, 22 дома из 27)."""
    cornice = next(e for e in house.facades[FRONT].elements if e.cls is ElementClass.CORNICE)
    door = _door(house)
    low = _edit(house, FRONT, cornice.id, y_m=door.y_m + door.h_m - 0.3)
    assert Rule.CORNICE in _rules(low, cfg)
    assert Rule.CORNICE not in _rules(house, cfg)


def test_trims_of_different_openings_overlap(clean, cfg):
    """Выводимый элемент одного проёма на другом проёме — налезание (gf#242: ставни окна на
    соседнем, козырёк двери на окне); свой подоконник под окном — нет."""
    w = _window(clean)
    blind = Element(id="b_w", cls=ElementClass.BLIND, x_m=w.x_m + w.w_m - 0.2, y_m=w.y_m,
                    w_m=0.5, h_m=w.h_m, parent="upper")
    found = validate(_added(clean, SIDE, blind), cfg.checks)
    assert [v.rule for v in found] == [Rule.OVERLAP]


def test_wall_without_finish(house, cfg):
    """Отделка на полстены — белая стена, поверх облицовка (gf#242): основная зона короче стены
    — брак, и часть стены без зоны — брак."""
    length = house.facades[SIDE].side.length_m
    half = _zones(house, SIDE, _rect(ZoneRole.MAIN, 0, 0, length / 2, house.spec.eaves_m))
    found = [v for v in validate(half, cfg.checks) if v.rule is Rule.FINISH]
    assert len(found) == 2  # зона короче стены и стена без отделки


def test_accent_ends_on_a_support(house, cfg):
    """Акцент доходит по ширине или по высоте до края стены, отметки, проёма или зоны во всю
    длину: полоса у входа (стаб) — не брак; вставка посреди стены — брак."""
    f, eaves = house.facades[FRONT], house.spec.eaves_m
    base = [z for z in f.zones if z.role is not ZoneRole.ACCENT]
    floating = _zones(house, FRONT, *base, _rect(ZoneRole.ACCENT, 2.9, 1.6, 3.6, 2.4))
    corner = _zones(house, FRONT, *base, _rect(ZoneRole.ACCENT, 0, 0.5, 0.6, eaves))
    assert Rule.FINISH in _rules(floating, cfg)
    assert Rule.FINISH not in _rules(corner, cfg)
    assert Rule.FINISH not in _rules(house, cfg)


def test_defects_by_kind(house, cfg):
    """Брак листа по видам (gf#242) — одна функция для датчика и метрики: у каждого вида —
    его нарушения."""
    door = _door(house)
    found = defects(_edit(house, FRONT, door.id, h_m=0.1), cfg.checks)
    assert set(found) == set(DEFECTS)
    assert [v.element for v in found[Rule.DOOR_LOW]] == [door.id]
    assert not any(found[r] for r in DEFECTS if r is not Rule.DOOR_LOW)


def test_plan_window_in_forbidden_zone_is_a_warning(lay_out, simple_svg, cfg):
    """Сценарий «Стена в окне плана» (`evaluation: Окно плана в запретной зоне`, gf#156): режим 2,
    окно плана там, куда упирается внутренняя стена, — предупреждение, ошибок нет."""
    found = validate(lay_out(svg=simple_svg(before_leaf(WALL_INTO_WINDOW))), cfg.checks)
    assert {(v.rule, v.side, v.severity) for v in found} == {
        (Rule.PLAN_FORBIDDEN, 2, Severity.WARNING)}


def test_model_window_in_forbidden_zone_is_an_error(lay_out, simple_svg, cfg):
    """То же окно, но поставленное моделью (x не задан планом), — ошибка."""
    sheet = lay_out(svg=simple_svg(before_leaf(WALL_INTO_WINDOW)))
    f = sheet.facades[2]
    w = next(e for e in f.elements if e.cls is ElementClass.WINDOW and e.fixed)
    found = _rules(_edit(sheet, 2, w.id, fixed=[]), cfg)
    assert Rule.FORBIDDEN in found and Rule.PLAN_FORBIDDEN not in found


def test_forbidden_zones_hold_only_on_ground_floor(lay_out, simple_svg, cfg):
    """`evaluation: Запретные зоны — по плану этажа`: у верхних этажей плана нет — окно модели
    второго этажа над примыканием перегородки первого не ошибка; то же окно на первом — ошибка."""
    sheet = lay_out(svg=simple_svg(before_leaf(WALL_INTO_WINDOW)))
    w = next(e for e in sheet.facades[2].elements if e.cls is ElementClass.WINDOW and e.fixed)
    upper = _edit(sheet, 2, w.id, fixed=[], floor=2)
    assert Rule.FORBIDDEN in _rules(_edit(sheet, 2, w.id, fixed=[]), cfg)
    assert {Rule.FORBIDDEN, Rule.PLAN_FORBIDDEN}.isdisjoint(_rules(upper, cfg))


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


def test_snap_returns_plan_window_to_its_opening(lay_out, cfg):
    """Режим 2: место и ширину окна задаёт план — модель поставила их неточно, шаг 5 ставит
    окно на проём плана, подоконник едет следом (`generation: Проёмы плана на месте`)."""
    sheet = lay_out()
    w = _window(sheet, floor=1)
    sill_dx = _sill(sheet, w.id).x_m - w.x_m
    off = _edit(sheet, SIDE, w.id, x_m=w.x_m + 0.1, w_m=w.w_m - 0.2)
    assert Rule.PLAN_OPENING in _rules(off, cfg)
    snapped = snap(off, cfg.checks)
    assert _window(snapped, floor=1) == w
    assert _sill(snapped, w.id).x_m - w.x_m == pytest.approx(sill_dx - 0.1)
    assert Rule.PLAN_OPENING not in _rules(snapped, cfg)



def test_snap_drops_repeated_plan_window(lay_out, cfg):
    """Модель повторила окно плана: две копии «заданы планом», проём — один. Лишняя копия и её
    подоконник убираются, проёмы больше не пересекаются (gf#153)."""
    sheet = lay_out()
    f = sheet.facades[SIDE]
    w = _window(sheet, floor=1)
    copy = w.model_copy(update={"id": "copy", "x_m": w.x_m + 0.05, "w_m": w.w_m - 0.1})
    copy_sill = _sill(sheet, w.id).model_copy(update={"id": "copy_sill", "parent": "copy"})
    facades = list(sheet.facades)
    facades[SIDE] = f.model_copy(update={"elements": [*f.elements, copy, copy_sill]})
    doubled = sheet.model_copy(update={"facades": facades})
    assert Rule.OVERLAP in _rules(doubled, cfg)
    snapped = snap(doubled, cfg.checks)
    assert {e.id for e in snapped.facades[SIDE].elements} == {e.id for e in f.elements}
    assert errors(validate(snapped, cfg.checks)) == []

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
