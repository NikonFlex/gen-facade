"""Шаг 5: валидатор фасадов
(`evaluation: Ошибки геометрии`, `evaluation: Предупреждения выравнивания`).

Ошибки: SVG не разбирается; элемент вне силуэта; проёмы или выводимые элементы разных проёмов
пересекаются; окно в запретной зоне; проём плана пропал или смещён; отметки на углах не сходятся;
геометрический брак листа (gf#242) — дверь ниже нормы свода, карниз на проёме, обрыв отделки.
Предупреждения: у окон этажа верх не на одной линии, окна разных этажей почти (но не точно) на
одной оси; скатная крыша над непрямоугольным контуром пока не строится (gf#320).
Стена — силуэт до карниза и фронтон над ним (roof.py): окно во фронтоне — в стене, а к скату
не ближе отступа `slope_offset_m` (gf#321).
Вложенность (подоконник у своего окна, наличник вокруг) — не нарушение: пересечения
проверяются между проёмами, каждый — со своими выводимыми элементами.
"""

from collections.abc import Mapping
from itertools import combinations
from math import inf
from xml.etree import ElementTree

import shapely

from genfacade import parts, roof, window_shape
from genfacade.config import Checks
from genfacade.derive import TRIM_OF
from genfacade.render.parse import parse_sheet_svg
from genfacade.schema import (
    EPS,
    OPENINGS,
    Element,
    ElementClass,
    FacadeSheet,
    FixedField,
    ForbiddenZone,
    GuidelineCheck,
    HouseSpec,
    MaterialZone,
    Polygon,
    RoofKind,
    Rule,
    Severity,
    SideFacade,
    VariantKind,
    Violation,
    ZoneRole,
)

WARNINGS = {Rule.FLOOR_ALIGN, Rule.AXIS_ALIGN, Rule.PLAN_FORBIDDEN,
            Rule.ROOF_FLAT}  # остальные — ошибки
# Геометрический брак листа (gf#242, хозяин 31.10): по этим правилам считает датчик и метрика.
DEFECTS = (Rule.DOOR_LOW, Rule.PANES, Rule.CORNICE, Rule.OUTSIDE, Rule.OVERLAP, Rule.FINISH,
           Rule.SLOPE)
FULL_LENGTH = (ZoneRole.PLINTH, ZoneRole.MAIN, ZoneRole.BAND)  # зоны во всю длину стены


def validate(sheet: FacadeSheet, cfg: Checks) -> list[Violation]:
    out = []
    for f, above in zip(sheet.facades, roof.sheet_gables(sheet), strict=True):
        out += _outside(f, above, sheet.spec, cfg) + _slope(f, above, sheet.spec, cfg)
        out += _overlaps(f, cfg) + _forbidden(f, cfg) + _plan_openings(f, cfg)
        out += _door_low(f, sheet.spec, cfg) + _panes(f, cfg) + _cornice(f, cfg)
        out += _finish(f, sheet.spec, cfg)
        out += _floor_align(f, cfg) + _axis_align(f, cfg)
    return out + _corners(sheet, cfg) + _roof(sheet)


def _roof(sheet: FacadeSheet) -> list[Violation]:
    """Скатная крыша над контуром не из четырёх сторон пока не строится (roof.py): лист без
    скатов — предупреждение, а не брак стены."""
    kind = sheet.spec.roof.kind
    if kind is RoofKind.FLAT or roof.builds(sheet):
        return []
    return [Violation(rule=Rule.ROOF_FLAT, severity=Severity.WARNING,
                      message=f"крыша {kind} над контуром из {len(sheet.facades)} сторон пока не "
                              f"строится — на листе без скатов (gf#320)")]


def defects(sheet: FacadeSheet, cfg: Checks) -> dict[Rule, list[Violation]]:
    """Геометрический брак листа по видам (gf#242): правило из DEFECTS → его нарушения на листе
    (пустой список — брака этого вида нет). Одна функция для датчика, метрики и конвейера."""
    found = validate(sheet, cfg)
    return {rule: [v for v in found if v.rule is rule] for rule in DEFECTS}


def validate_svg(text: str, sheet: FacadeSheet, cfg: Checks) -> list[Violation]:
    """Элементы и зоны — из SVG, стороны и силуэты — из листа: проверяется то, что на чертеже."""
    try:
        parsed = parse_sheet_svg(text)
        facades = [f.model_copy(update=dict(zip(("elements", "zones"), parsed[f.side.index],
                                                strict=True)))
                   for f in sheet.facades]
    except (ElementTree.ParseError, KeyError, ValueError) as e:
        return [Violation(rule=Rule.SVG_PARSE, severity=Severity.ERROR,
                          message=f"SVG не разбирается: {e}")]
    return validate(sheet.model_copy(update={"facades": facades}), cfg)


def errors(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity is Severity.ERROR]


def _v(f: SideFacade, rule: Rule, e: Element | None, message: str) -> Violation:
    return Violation(rule=rule, severity=Severity.WARNING if rule in WARNINGS else Severity.ERROR,
                     side=f.side.index, element=e.id if e else None, message=message)


def _box(e: Element) -> shapely.Polygon:
    return shapely.box(e.x_m, e.y_m, e.x_m + e.w_m, e.y_m + e.h_m)


def _hits(a: Element, b: Element, cfg: Checks) -> bool:
    """Налезает больше, чем на допуск: касание — не пересечение."""
    return _box(a).intersection(_box(b)).area > cfg.eps_m ** 2


def _owners(f: SideFacade) -> dict[str, str]:
    """Проём и его выводимые элементы (ребёнок проёма класса из derive.TRIM_OF) → имя проёма."""
    openings = {e.id for e in f.elements if e.cls in OPENINGS}
    return {e.id: e.id if e.id in openings else e.parent for e in f.elements
            if e.id in openings or (e.cls in TRIM_OF and e.parent in openings)}


def _outside(f: SideFacade, above: Polygon | None, spec: HouseSpec,
             cfg: Checks) -> list[Violation]:
    """Элемент — в силуэте стены, а на стене с фронтоном — в силуэте с фронтоном (gf#321)."""
    wall = shapely.Polygon(f.silhouette or [])
    if above is not None:  # у стены со ступенями силуэт уже её форма: карниз дома не её высота
        wall = wall.union(shapely.Polygon(above) if f.silhouette else
                          roof.wall_shape(f.side.length_m, spec.eaves_m, above))
    wall = wall.buffer(cfg.eps_m, join_style="mitre")
    room = _room(f, above, spec, cfg)
    by = {e.id: e for e in f.elements}
    return [_v(f, Rule.OUTSIDE, e, f"{e.cls} {e.id} выходит за силуэт стены")
            for e in f.elements if not wall.contains(_drawn(e, room, by))]


def _room(f: SideFacade, above: Polygon | None, spec: HouseSpec,
          cfg: Checks) -> window_shape.Gable | None:
    return window_shape.gable_room(f.side.length_m, spec.eaves_m, above, cfg.slope_offset_m)


def _drawn(e: Element, room: window_shape.Gable | None,
           by: dict[str, Element] | None = None) -> shapely.Polygon:
    """Что элемент занимает на стене: рамка, а у окна — контур по виду (окно по скату — рамка,
    срезанная скатами, gf#319, gf#470), у наличника такого окна — контур наличника."""
    if e.cls is ElementClass.MOLDING and by is not None and (w := by.get(e.parent or "")):
        if w.cls is ElementClass.WINDOW:
            return shapely.Polygon(window_shape.casing(w, e, room))
    if e.cls is not ElementClass.WINDOW:
        return _box(e)
    return shapely.Polygon(window_shape.outline(e, room))


def _slope(f: SideFacade, above: Polygon | None, spec: HouseSpec,
           cfg: Checks) -> list[Violation]:
    """Окно во фронтоне (верх выше карниза) — не ближе `slope_offset_m` к скату (gf#321). Окно,
    пересекающее скат, — ещё и `outside`. Окно вида `slope` (gf#319) проверяется по контуру: рамка
    может выйти за скат, но контур — не меньше `slope_share` рамки."""
    if above is None:
        return []
    gable = _room(f, above, spec, cfg)
    wide = gable.room.buffer(cfg.eps_m)
    near = f"ближе {cfg.slope_offset_m:.2f} м к скату"
    out = [_v(f, Rule.SLOPE, e, f"окно {e.id} во фронтоне {near}")
           for e in f.elements if roof.over_eaves(e, spec.eaves_m + cfg.eps_m)
           and not wide.contains(_drawn(e, gable))]
    small = [e for e in f.elements if window_shape.kind(e) is VariantKind.SLOPE
             and roof.over_eaves(e, spec.eaves_m + cfg.eps_m)
             and window_shape.reach(gable.room, e.x_m, e.y_m, e.w_m, e.h_m) < cfg.slope_share - EPS]
    return out + [_v(f, Rule.SLOPE, e, f"окно {e.id} по скату: за скатом больше "
                     f"{1 - cfg.slope_share:.0%} рамки") for e in small
                  if all(v.element != e.id for v in out)]


def _overlaps(f: SideFacade, cfg: Checks) -> list[Violation]:
    """Проёмы и выводимые элементы разных проёмов не налезают друг на друга: ставни окна на
    соседнем окне, козырёк двери на окне — брак (gf#242); свои подоконник и наличник — нет."""
    owner = _owners(f)
    items = [e for e in f.elements if e.id in owner]
    return [_v(f, Rule.OVERLAP, a, f"проёмы {a.id} и {b.id} пересекаются"
               if a.id == owner[a.id] and b.id == owner[b.id]
               else f"{a.cls} {a.id} и {b.cls} {b.id} разных проёмов пересекаются")
            for a, b in combinations(items, 2)
            if owner[a.id] != owner[b.id] and _hits(a, b, cfg)]


def door_min_m(norm: Mapping, spec: HouseSpec, door: Element) -> float:
    """Самая низкая дверь по норме `door_height`: `min`, а при низком этаже — не больше доли
    `floor_share` высоты его этажа (gf#413: у ffh-halfstory этаж 1,42 м, дверь 1,42 м)."""
    floor = min(door.floor or 1, spec.floors)
    return min(norm["min"], norm.get("floor_share", inf) * spec.floor_heights_m[floor - 1])


def _door_low(f: SideFacade, spec: HouseSpec, cfg: Checks) -> list[Violation]:
    """Дверь не ниже нормы свода с `use = ["validate"]` (door_height, gf#242): дверь 0,05 м
    модели — не дверь."""
    norm = cfg.norms.get(GuidelineCheck.DOOR_HEIGHT)
    if norm is None:
        return []
    return [_v(f, Rule.DOOR_LOW, e, f"дверь {e.id} высотой {e.h_m:.2f} м — ниже {low:.2f} м")
            for e in f.elements if e.cls is ElementClass.DOOR
            and e.h_m + cfg.eps_m < (low := door_min_m(norm, spec, e))]


def _panes(f: SideFacade, cfg: Checks) -> list[Violation]:
    """Ячейка стекла окна не уже `pane_min_w_m` и не ниже `pane_min_h_m` (gf#413): окно 0,74 м с
    сеткой 9 × 9 — не окно; сетка у окна, а не у двери (у двери — филёнки)."""
    return [_v(f, Rule.PANES, e, f"окно {e.id}: ячейка {e.w_m / e.variant.cols:.2f} × "
               f"{e.h_m / e.variant.rows:.2f} м — меньше {cfg.pane_min_w_m:.2f} × "
               f"{cfg.pane_min_h_m:.2f} м")
            for e in f.elements if e.cls is ElementClass.WINDOW and e.variant is not None
            and (e.w_m / e.variant.cols + cfg.eps_m < cfg.pane_min_w_m
                 or e.h_m / e.variant.rows + cfg.eps_m < cfg.pane_min_h_m)]


def _cornice(f: SideFacade, cfg: Checks) -> list[Violation]:
    """Карниз не заходит на проём и на его выводимые элементы: окно под карнизом — брак (gf#242)."""
    owner = _owners(f)
    return [_v(f, Rule.CORNICE, e, f"карниз {c.id} заходит на {e.cls} {e.id}")
            for c in f.elements if c.cls is ElementClass.CORNICE
            for e in f.elements if e.id in owner and _hits(c, e, cfg)]


def _finish(f: SideFacade, spec: HouseSpec, cfg: Checks) -> list[Violation]:
    """Отделка без обрывов (gf#242): стена покрыта зонами — дыра шире допуска на чертеже белая;
    цоколь, основная и пояс — во всю длину; остальные зоны доходят до края, отметки или проёма
    (`_anchored`)."""
    wall = shapely.Polygon(f.silhouette or [])
    drawn = [shapely.Polygon(z.shape) for z in f.zones]
    # контур, пересекающий сам себя, — брак ответа; GEOS на нём падает, поэтому площадь — по
    # исправленному make_valid
    out = [_v(f, Rule.FINISH, None, f"контур зоны {z.role} пересекает сам себя")
           for z, shape in zip(f.zones, drawn, strict=True) if not shape.is_valid]
    shapes = [shapely.make_valid(s) for s in drawn]
    bare = wall.difference(shapely.unary_union(shapes)) if shapes else wall
    if not bare.buffer(-cfg.eps_m / 2).is_empty:
        out.append(_v(f, Rule.FINISH, None, f"{bare.area:.2f} м² стены без отделки"))
    for z, shape in zip(f.zones, shapes, strict=True):
        box = shape.bounds
        lo, hi = _part_span(f, box)
        whole = box[0] <= lo + cfg.eps_m and box[2] >= hi - cfg.eps_m
        if not (whole if z.role in FULL_LENGTH else _anchored(box, f, spec, cfg)):
            out.append(_v(f, Rule.FINISH, None, f"зона {z.role} {_span(box)} обрывается "
                                                "посреди стены"))
    return out


def _part_span(f: SideFacade, box: tuple[float, ...]) -> tuple[float, float]:
    """Во всю длину — части стены, где стоит зона: у стены из частей разной высоты (gf#322) зона
    части идёт по её участку; у прямоугольной стены — вся стена."""
    middle = (box[0] + box[2]) / 2
    run = next((r for r in f.runs if r.x0_m <= middle <= r.x1_m), None)
    return (run.x0_m, run.x1_m) if run else (0.0, f.side.length_m)


def _span(box: tuple[float, ...]) -> str:
    x0, y0, x1, y1 = box
    return f"{x0:.2f}–{x1:.2f} × {y0:.2f}–{y1:.2f} м"


def _anchored(box: tuple[float, ...], f: SideFacade, spec: HouseSpec, cfg: Checks) -> bool:
    """Зона упирается по ширине (оба края) или по высоте (низ и верх) в опоры: края стены,
    отметки дома, края проёмов и зон во всю длину — полоса у входа, на углу, вставка в простенке,
    панель по низу. Допуск — snap_m, как у привязки: края зоны модели — на сетке токенов, а
    проёмы привязка двигает к плану и к общей оси."""
    x0, y0, x1, y1 = box
    xs, ys = _supports(f, spec)
    on = lambda v, at: any(abs(v - s) <= cfg.snap_m for s in at)  # noqa: E731
    return (on(x0, xs) and on(x1, xs)) or (on(y0, ys) and on(y1, ys))


def _supports(f: SideFacade, spec: HouseSpec) -> tuple[set[float], set[float]]:
    """Опоры зоны по x и по y."""
    ops = [e for e in f.elements if e.cls in OPENINGS]
    bands = [_bounds(z) for z in f.zones if z.role in FULL_LENGTH]
    xs = {0.0, f.side.length_m} | {e.x_m for e in ops} | {e.x_m + e.w_m for e in ops}
    xs |= {x for r in f.runs for x in (r.x0_m, r.x1_m)}  # границы частей дома (gf#322)
    ys = {0.0, spec.plinth_m, *spec.floor_levels()} | {e.y_m for e in ops}
    ys |= {r.eaves_m for r in f.runs}
    ys |= {e.y_m + e.h_m for e in ops} | {y for b in bands for y in (b[1], b[3])}
    return xs, ys


def _bounds(z: MaterialZone) -> tuple[float, ...]:
    return shapely.Polygon(z.shape).bounds


def _forbidden(f: SideFacade, cfg: Checks) -> list[Violation]:
    """Окно модели в запретной зоне — ошибка. Окно плана (x задан планом) — предупреждение: план
    главнее, его окно не двигается (`evaluation: Окно плана в запретной зоне`). Зоны плана — по
    первому этажу: у верхних этажей плана нет, их перегородок мы не знаем (`evaluation: Запретные
    зоны — по плану этажа`). Зона под кровлей соседней нижней части (у неё есть высота, gf#412) —
    на любом этаже: окно, у которого кровля закрывает больше `slope_share` рамки (как «окно по
    скату»), срезано ею."""
    windows = [e for e in f.elements if e.cls is ElementClass.WINDOW]
    return [_v(f, Rule.PLAN_FORBIDDEN if FixedField.X in e.fixed else Rule.FORBIDDEN, e,
               f"окно {'плана ' if FixedField.X in e.fixed else ''}{e.id} в запретной зоне "
               f"{z.x0_m:.2f}–{z.x1_m:.2f} м" + _under_roof(z))
            for e in windows for z in f.side.forbidden if _in_zone(e, z, cfg)]


def _in_zone(e: Element, z: ForbiddenZone, cfg: Checks) -> bool:
    """Окно в зоне: у зоны плана рамка заходит на неё по x на первом этаже; у зоны под кровлей —
    кровля закрывает больше `slope_share` площади рамки."""
    along = min(e.x_m + e.w_m, z.x1_m) - max(e.x_m, z.x0_m)
    if z.y0_m is None or z.y1_m is None:
        return along > cfg.eps_m and (e.floor or 1) == 1
    high = min(e.y_m + e.h_m, z.y1_m) - max(e.y_m, z.y0_m)
    return along > cfg.eps_m and high > cfg.eps_m and (
        along * high > cfg.slope_share * e.w_m * e.h_m)


def _under_roof(z: ForbiddenZone) -> str:
    return "" if z.y0_m is None else f" под кровлей соседней части ({z.y0_m:.2f}–{z.y1_m:.2f} м)"


def _plan_openings(f: SideFacade, cfg: Checks) -> list[Violation]:
    """Каждый проём плана — на первом этаже с теми же x и шириной; у стены из частей проём на
    границе частей — внутри своей части (`parts.clamped`)."""
    ground = [e for e in f.elements if e.cls in OPENINGS and e.floor == 1]
    return [_v(f, Rule.PLAN_OPENING, None,
               f"проём плана {o.kind} x={o.x_m:.2f} м пропал или смещён")
            for o in (parts.clamped(o, f.runs) for o in f.side.openings)
            if not any(abs(e.x_m - o.x_m) <= cfg.eps_m and abs(e.w_m - o.width_m) <= cfg.eps_m
                       for e in ground)]


def _run_of(f: SideFacade, e: Element) -> int | None:
    """Участок стены (часть дома, gf#322), где стоит элемент; у стены без участков — None: линия
    верха окон у каждой части своя."""
    middle = e.x_m + e.w_m / 2
    return next((j for j, r in enumerate(f.runs) if r.x0_m <= middle <= r.x1_m), None)


def _floor_align(f: SideFacade, cfg: Checks) -> list[Violation]:
    """Окна одного этажа — верхом на одной линии. Низ бывает разный намеренно: маленькое
    окно санузла, окно в пол (хозяин 01.10) — за него не предупреждаем."""
    out, by_floor = [], {}
    for w in (e for e in f.elements if e.cls is ElementClass.WINDOW):
        by_floor.setdefault((w.floor, _run_of(f, w)), []).append(w)
    for ws in by_floor.values():
        for a, b in combinations(ws, 2):
            if abs((a.y_m + a.h_m) - (b.y_m + b.h_m)) > cfg.align_m:
                out.append(_v(f, Rule.FLOOR_ALIGN, b,
                              f"у окон {a.id} и {b.id} этажа верх на разной высоте"))
    return out


def _axis_align(f: SideFacade, cfg: Checks) -> list[Violation]:
    """Окна разных этажей почти на одной оси — скорее промах, чем замысел."""
    ws = [e for e in f.elements if e.cls is ElementClass.WINDOW]
    return [_v(f, Rule.AXIS_ALIGN, b, f"окна {a.id} и {b.id} почти на одной оси")
            for a, b in combinations(ws, 2)
            if a.floor != b.floor
            and cfg.eps_m < abs((a.x_m + a.w_m / 2) - (b.x_m + b.w_m / 2)) <= cfg.align_m]


def _edge_height(f: SideFacade, x: float) -> float:
    return max(y for px, y in f.silhouette or [(x, 0.0)] if abs(px - x) <= EPS)


def _edge_part(f: SideFacade, left: bool) -> int | None:
    """Часть дома у края стены (левого или правого); у стены без участков — None."""
    return (f.runs[0] if left else f.runs[-1]).part if f.runs else None


def _corners(sheet: FacadeSheet, cfg: Checks) -> list[Violation]:
    """Угол i+1: левый край стороны i (x = 0) и правый край стороны i+1 (x = длина). У стен одной
    части высоты равны. На стыке двух частей (gf#322) нижняя стена упирается в стену выше — высоты
    разные по замыслу, угол не сверяется."""
    out, fs = [], sheet.facades
    for a, b in zip(fs, fs[1:] + fs[:1], strict=True):
        if _edge_part(a, True) != _edge_part(b, False):
            continue
        ha, hb = _edge_height(a, 0.0), _edge_height(b, b.side.length_m)
        if abs(ha - hb) > cfg.eps_m:
            out.append(_v(a, Rule.CORNER, None,
                          f"угол сторон {a.side.index} и {b.side.index}: {ha:.2f} ≠ {hb:.2f} м"))
    return out
