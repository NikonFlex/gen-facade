"""Шаг 5: валидатор фасадов (specs/evaluation.md, правило 1).

Ошибки: SVG не разбирается; элемент вне силуэта; проёмы пересекаются; окно в запретной зоне;
проём плана пропал или смещён; отметки на углах не сходятся. Предупреждения: у окон этажа
верх не на одной линии, окна разных этажей почти (но не точно) на одной оси.
Вложенность (подоконник у окна, наличник вокруг) — не нарушение: пересечения проверяются
только между проёмами.
"""

from itertools import combinations
from xml.etree import ElementTree

import shapely

from genfacade.config import Checks
from genfacade.render.parse import parse_sheet_svg
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    Rule,
    Severity,
    SideFacade,
    Violation,
)

OPENINGS = (ElementClass.WINDOW, ElementClass.DOOR, ElementClass.GARAGE_DOOR)
WARNINGS = {Rule.FLOOR_ALIGN, Rule.AXIS_ALIGN}  # остальные правила — ошибки


def validate(sheet: FacadeSheet, cfg: Checks) -> list[Violation]:
    out = []
    for f in sheet.facades:
        out += _outside(f, cfg) + _overlaps(f, cfg) + _forbidden(f, cfg) + _plan_openings(f, cfg)
        out += _floor_align(f, cfg) + _axis_align(f, cfg)
    return out + _corners(sheet, cfg)


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


def _outside(f: SideFacade, cfg: Checks) -> list[Violation]:
    wall = shapely.Polygon(f.silhouette or []).buffer(cfg.eps_m, join_style="mitre")
    return [_v(f, Rule.OUTSIDE, e, f"{e.cls} {e.id} выходит за силуэт стены")
            for e in f.elements if not wall.contains(_box(e))]


def _overlaps(f: SideFacade, cfg: Checks) -> list[Violation]:
    ops = [e for e in f.elements if e.cls in OPENINGS]
    return [_v(f, Rule.OVERLAP, a, f"проёмы {a.id} и {b.id} пересекаются")
            for a, b in combinations(ops, 2)
            if _box(a).intersection(_box(b)).area > cfg.eps_m ** 2]


def _forbidden(f: SideFacade, cfg: Checks) -> list[Violation]:
    return [_v(f, Rule.FORBIDDEN, e, f"окно {e.id} в запретной зоне {z.x0_m:.2f}–{z.x1_m:.2f} м")
            for e in f.elements if e.cls is ElementClass.WINDOW for z in f.side.forbidden
            if min(e.x_m + e.w_m, z.x1_m) - max(e.x_m, z.x0_m) > cfg.eps_m]


def _plan_openings(f: SideFacade, cfg: Checks) -> list[Violation]:
    """Каждый проём плана — на первом этаже с теми же x и шириной."""
    ground = [e for e in f.elements if e.cls in OPENINGS and e.floor == 1]
    return [_v(f, Rule.PLAN_OPENING, None,
               f"проём плана {o.kind} x={o.x_m:.2f} м пропал или смещён")
            for o in f.side.openings
            if not any(abs(e.x_m - o.x_m) <= cfg.eps_m and abs(e.w_m - o.width_m) <= cfg.eps_m
                       for e in ground)]


def _floor_align(f: SideFacade, cfg: Checks) -> list[Violation]:
    """Окна одного этажа — верхом на одной линии. Низ бывает разный намеренно: маленькое
    окно санузла, окно в пол (хозяин 01.10) — за него не предупреждаем."""
    out, by_floor = [], {}
    for w in (e for e in f.elements if e.cls is ElementClass.WINDOW):
        by_floor.setdefault(w.floor, []).append(w)
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


def _corners(sheet: FacadeSheet, cfg: Checks) -> list[Violation]:
    """Угол i+1: левый край стороны i (x = 0) и правый край стороны i+1 (x = длина)."""
    out, fs = [], sheet.facades
    for a, b in zip(fs, fs[1:] + fs[:1], strict=True):
        ha, hb = _edge_height(a, 0.0), _edge_height(b, b.side.length_m)
        if abs(ha - hb) > cfg.eps_m:
            out.append(_v(a, Rule.CORNER, None,
                          f"угол сторон {a.side.index} и {b.side.index}: {ha:.2f} ≠ {hb:.2f} м"))
    return out
