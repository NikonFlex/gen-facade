"""Свод правил фасада (gf#209): проверка правил из config/guidelines.toml по листу фасадов.

Правило проверяется на доме по случаям — окнам, проёмам, стенам, этажам; дом выполняет правило,
если выполнены все его случаи, а случаев нет — правило к дому неприменимо. Этаж и отметка пола
окна — как у метрик (metrics/measures.py): по высоте низа, а не по полю `floor`, которое пишет
сам метод. Параметры правила — в метрах, их имена у каждого вида проверки — PARAMS.
"""

from collections.abc import Callable
from math import inf
from pathlib import Path
from statistics import mean

from pydantic import BaseModel

from genfacade.config import Config, Guideline
from genfacade.datasets import store
from genfacade.metrics.measures import floor_of, level_of
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    GuidelineCheck,
    Plan,
    Sample,
    SideFacade,
    Source,
    signed_area,
)
from genfacade.validate import OPENINGS

Params = dict[str, ElementClass | float | list[float]]
Check = Callable[[Params, FacadeSheet, Plan | None], list[bool]]
COVERS = (ElementClass.CANOPY, ElementClass.PORCH)  # что закрывает вход сверху


def cases(g: Guideline, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Случаи правила на доме: выполнен ли каждый."""
    return CHECKS[g.check](g.params, sheet, plan)


# ——— выборки ———

def _of(f: SideFacade, cls: ElementClass) -> list[Element]:
    return [e for e in f.elements if e.cls is cls]


def _openings(f: SideFacade) -> list[Element]:
    return [e for e in f.elements if e.cls in OPENINGS]


def _floors(es: list[Element], sheet: FacadeSheet) -> dict[int, list[Element]]:
    """Элементы по этажам, слева направо."""
    out: dict[int, list[Element]] = {}
    for e in sorted(es, key=lambda e: e.x_m):
        out.setdefault(floor_of(e, sheet.spec), []).append(e)
    return out


def _within(v: float, p: Params) -> bool:
    return p.get("min", -inf) - EPS <= v <= p.get("max", inf) + EPS


def _near(v: float, row: list[float], tol: float) -> bool:
    return any(abs(v - r) <= tol + EPS for r in row)


def _top(e: Element) -> float:
    return e.y_m + e.h_m


def _center(e: Element) -> float:
    return e.x_m + e.w_m / 2


def _entrance_doors(f: SideFacade, sheet: FacadeSheet) -> list[Element]:
    """Двери первого этажа стены входа; у других стен — ни одной."""
    doors = _floors(_of(f, ElementClass.DOOR), sheet).get(1, [])
    return doors if f.side.has_entrance else []


# ——— размеры и пропорции ———

def aspect(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    return [_within(e.h_m / e.w_m, p) for f in sheet.facades for e in _of(f, p["cls"])]


def size_row(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    tol, heights = p["tol_m"], p.get("heights", [])
    return [_near(e.w_m, p["widths"], tol) and (not heights or _near(e.h_m, heights, tol))
            for f in sheet.facades for e in _of(f, p["cls"])]


def module(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    m = p["module_m"]
    return [all(abs(v - round(v / m) * m) <= p["tol_m"] + EPS for v in (e.w_m, e.h_m))
            for f in sheet.facades for e in _of(f, p["cls"])]


def door_size(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    return [e.w_m + EPS >= p["min_w"] and e.h_m + EPS >= p["min_h"]
            and e.w_m <= p.get("max_w", inf) + EPS and e.h_m <= p.get("max_h", inf) + EPS
            for f in sheet.facades for e in _of(f, ElementClass.DOOR)]


def window_types(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Размеров окон на фасаде и на доме не больше заданного; размеры ближе tol — один."""
    def count(ws: list[Element]) -> int:
        kinds: list[Element] = []
        for w in ws:
            if not any(abs(w.w_m - k.w_m) <= p["tol_m"] and abs(w.h_m - k.h_m) <= p["tol_m"]
                       for k in kinds):
                kinds.append(w)
        return len(kinds)
    per_wall = [count(_of(f, ElementClass.WINDOW)) <= p["per_facade"] for f in sheet.facades]
    every = [w for f in sheet.facades for w in _of(f, ElementClass.WINDOW)]
    return [*per_wall, count(every) <= p["per_house"]] if every else []


def shutter_width(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Ставня к ширине своего окна (родитель — окно)."""
    out = []
    for f in sheet.facades:
        by_id = {w.id: w for w in _of(f, ElementClass.WINDOW)}
        out += [_within(b.w_m / by_id[b.parent].w_m, p)
                for b in _of(f, ElementClass.BLIND) if b.parent in by_id]
    return out


# ——— высоты ———

def sill_height(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Низ окна над полом своего этажа; окна в пол (ниже skip_below_m) не в счёт."""
    sills = [w.y_m - level_of(w, sheet.spec) for f in sheet.facades
             for w in _of(f, ElementClass.WINDOW)]
    return [_within(s, p) for s in sills if s + EPS >= p["skip_below_m"]]


def head_height(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    return [_within(_top(w) - level_of(w, sheet.spec), p)
            for f in sheet.facades for w in _of(f, ElementClass.WINDOW)]


def head_to_eaves(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Фриз над окном верхнего этажа: от верха окна с наличником до низа карниза над ним, а
    без карниза — до отметки карниза дома. От отметки зазор засчитывал окно, упёртое в карниз
    0,25 м (gf#212)."""
    spec = sheet.spec
    return [_eaves_line(f, w, spec.eaves_m) - _head(f, w) + EPS >= p["min"]
            for f in sheet.facades for w in _of(f, ElementClass.WINDOW)
            if floor_of(w, spec) == spec.floors]


def _head(f: SideFacade, w: Element) -> float:
    """Верх окна вместе с наличником (у наличника родитель — окно)."""
    return max([_top(w), *(_top(m) for m in _of(f, ElementClass.MOLDING) if m.parent == w.id)])


def _eaves_line(f: SideFacade, w: Element, eaves_m: float) -> float:
    """Низ карниза стены над окном; карниза нет — отметка карниза дома."""
    above = [c.y_m for c in _of(f, ElementClass.CORNICE) if c.y_m + EPS >= _top(w)
             and c.x_m < w.x_m + w.w_m and c.x_m + c.w_m > w.x_m]
    return min([eaves_m, *above])


def plinth_height(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    return [_within(sheet.spec.plinth_m, p)]


def floor_height(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    return [_within(h, p) for h in sheet.spec.floor_heights_m]


# ——— расстановка ———

def head_line(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Верх окон этажа стены (и дверей, если doors = 1) на одной линии."""
    cls = OPENINGS if p.get("doors") else (ElementClass.WINDOW,)
    out = []
    for f in sheet.facades:
        for es in _floors([e for e in f.elements if e.cls in cls], sheet).values():
            if len(es) > 1:
                tops = [_top(e) for e in es]
                out.append(max(tops) - min(tops) <= p["tol_m"] + EPS)
    return out


def vertical_axes(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Окно верхнего этажа стоит центром над окном этажа ниже."""
    out = []
    for f in sheet.facades:
        floors = _floors(_of(f, ElementClass.WINDOW), sheet)
        for n, ws in floors.items():
            below = floors.get(n - 1, [])
            out += [any(abs(_center(w) - _center(v)) <= p["tol_m"] + EPS for v in below)
                    for w in ws if below]
    return out


def corner_distance(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    return [min(e.x_m, f.side.length_m - e.x_m - e.w_m) + EPS >= p["min"]
            for f in sheet.facades for e in _of(f, p["cls"])]


def pier_min(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Простенок между соседними проёмами этажа не уже min."""
    out = []
    for f in sheet.facades:
        for es in _floors(_openings(f), sheet).values():
            pairs = zip(es, es[1:], strict=False)
            out += [b.x_m - a.x_m - a.w_m + EPS >= p["min"] for a, b in pairs]
    return out


def door_head_line(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Верх двери первого этажа — на линии верха окон того же этажа стены."""
    out = []
    for f in sheet.facades:
        ground = _floors(_openings(f), sheet).get(1, [])
        tops = [_top(w) for w in ground if w.cls is ElementClass.WINDOW]
        out += [abs(_top(d) - mean(tops)) <= p["tol_m"] + EPS
                for d in ground if d.cls is ElementClass.DOOR and tops]
    return out


def lower_not_smaller(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Окна первого этажа стены не ниже окон верхних этажей (средняя высота)."""
    out = []
    for f in sheet.facades:
        floors = _floors(_of(f, ElementClass.WINDOW), sheet)
        if 1 in floors:
            first = mean(w.h_m for w in floors[1])
            out += [first + EPS >= mean(w.h_m for w in ws) for n, ws in floors.items() if n > 1]
    return out


def symmetry(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Стена входа: каждому проёму этажа есть зеркальный относительно оси входной двери."""
    out = []
    for f in sheet.facades:
        doors = _entrance_doors(f, sheet)
        if not doors:
            continue
        axis = _center(doors[0])
        for es in _floors(_openings(f), sheet).values():
            out += [any(abs(2 * axis - _center(e) - _center(m)) <= p["tol_m"] + EPS
                        and abs(e.w_m - m.w_m) <= p["tol_m"] + EPS for m in es) for e in es]
    return out


# ——— доли площади и ширины ———

def opening_share(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Площадь проёмов к площади стены от цоколя до карниза."""
    height = sheet.spec.eaves_m - sheet.spec.plinth_m
    return [_within(sum(e.w_m * e.h_m for e in _openings(f)) / (f.side.length_m * height), p)
            for f in sheet.facades]


def floor_opening_width(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """На каждом этаже стены — суммарная ширина проёмов к длине стены."""
    out = []
    for f in sheet.facades:
        floors = _floors(_openings(f), sheet)
        out += [_within(sum(e.w_m for e in floors.get(n, [])) / f.side.length_m, p)
                for n in range(1, sheet.spec.floors + 1)]
    return out


def light_ratio(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """Площадь окон дома к площади полов (контур плана × этажи)."""
    if plan is None:
        return []
    floor_area = abs(signed_area(plan.outline)) * sheet.spec.floors
    glass = sum(w.w_m * w.h_m for f in sheet.facades for w in _of(f, ElementClass.WINDOW))
    return [_within(glass / floor_area, p)]


# ——— зависимые элементы ———

def sill_under_window(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """У окна (не в пол) — подоконник: родитель — окно или полоса под его низом."""
    out = []
    for f in sheet.facades:
        sills = _of(f, ElementClass.SILL)
        for w in _of(f, ElementClass.WINDOW):
            if w.y_m - level_of(w, sheet.spec) + EPS >= p["skip_below_m"]:
                out.append(any(s.parent == w.id or _under(s, w, p["tol_m"]) for s in sills))
    return out


def _under(s: Element, w: Element, tol: float) -> bool:
    overlap = min(s.x_m + s.w_m, w.x_m + w.w_m) - max(s.x_m, w.x_m)
    return overlap >= w.w_m / 2 and abs(_top(s) - w.y_m) <= tol + EPS


def canopy_over_entrance(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    """На стене входа над дверью первого этажа — козырёк или навес крыльца."""
    out = []
    for f in sheet.facades:
        doors = _entrance_doors(f, sheet)
        if doors:
            covers = [c for c in f.elements if c.cls in COVERS]
            out.append(any(_covers(c, d) for c in covers for d in doors))
    return out


def _covers(c: Element, d: Element) -> bool:
    overlap = min(c.x_m + c.w_m, d.x_m + d.w_m) - max(c.x_m, d.x_m)
    return overlap > EPS and _top(c) + EPS >= _top(d)


def none(p: Params, sheet: FacadeSheet, plan: Plan | None) -> list[bool]:
    return []


CHECKS: dict[GuidelineCheck, Check] = {
    GuidelineCheck.NONE: none,
    GuidelineCheck.ASPECT: aspect,
    GuidelineCheck.SIZE_ROW: size_row,
    GuidelineCheck.MODULE: module,
    GuidelineCheck.SILL_HEIGHT: sill_height,
    GuidelineCheck.HEAD_HEIGHT: head_height,
    GuidelineCheck.HEAD_LINE: head_line,
    GuidelineCheck.VERTICAL_AXES: vertical_axes,
    GuidelineCheck.CORNER_DISTANCE: corner_distance,
    GuidelineCheck.PIER_MIN: pier_min,
    GuidelineCheck.OPENING_SHARE: opening_share,
    GuidelineCheck.FLOOR_OPENING_WIDTH: floor_opening_width,
    GuidelineCheck.WINDOW_TYPES: window_types,
    GuidelineCheck.DOOR_SIZE: door_size,
    GuidelineCheck.DOOR_HEAD_LINE: door_head_line,
    GuidelineCheck.SILL_UNDER_WINDOW: sill_under_window,
    GuidelineCheck.CANOPY_OVER_ENTRANCE: canopy_over_entrance,
    GuidelineCheck.SHUTTER_WIDTH: shutter_width,
    GuidelineCheck.PLINTH_HEIGHT: plinth_height,
    GuidelineCheck.FLOOR_HEIGHT: floor_height,
    GuidelineCheck.LIGHT_RATIO: light_ratio,
    GuidelineCheck.HEAD_TO_EAVES: head_to_eaves,
    GuidelineCheck.LOWER_NOT_SMALLER: lower_not_smaller,
    GuidelineCheck.SYMMETRY: symmetry,
}

# Имена параметров каждого вида проверки: обязательные и необязательные (опечатка — ошибка теста).
PARAMS: dict[GuidelineCheck, tuple[set[str], set[str]]] = {
    GuidelineCheck.NONE: (set(), set()),
    GuidelineCheck.ASPECT: ({"cls"}, {"min", "max"}),
    GuidelineCheck.SIZE_ROW: ({"cls", "widths", "tol_m"}, {"heights"}),
    GuidelineCheck.MODULE: ({"cls", "module_m", "tol_m"}, set()),
    GuidelineCheck.SILL_HEIGHT: ({"skip_below_m"}, {"min", "max"}),
    GuidelineCheck.HEAD_HEIGHT: (set(), {"min", "max"}),
    GuidelineCheck.HEAD_LINE: ({"tol_m"}, {"doors"}),
    GuidelineCheck.VERTICAL_AXES: ({"tol_m"}, set()),
    GuidelineCheck.CORNER_DISTANCE: ({"cls", "min"}, set()),
    GuidelineCheck.PIER_MIN: ({"min"}, set()),
    GuidelineCheck.OPENING_SHARE: (set(), {"min", "max"}),
    GuidelineCheck.FLOOR_OPENING_WIDTH: (set(), {"min", "max"}),
    GuidelineCheck.WINDOW_TYPES: ({"per_facade", "per_house", "tol_m"}, set()),
    GuidelineCheck.DOOR_SIZE: ({"min_w", "min_h"}, {"max_w", "max_h"}),
    GuidelineCheck.DOOR_HEAD_LINE: ({"tol_m"}, set()),
    GuidelineCheck.SILL_UNDER_WINDOW: ({"skip_below_m", "tol_m"}, set()),
    GuidelineCheck.CANOPY_OVER_ENTRANCE: (set(), set()),
    GuidelineCheck.SHUTTER_WIDTH: (set(), {"min", "max"}),
    GuidelineCheck.PLINTH_HEIGHT: (set(), {"min", "max"}),
    GuidelineCheck.FLOOR_HEIGHT: (set(), {"min", "max"}),
    GuidelineCheck.LIGHT_RATIO: (set(), {"min", "max"}),
    GuidelineCheck.HEAD_TO_EAVES: ({"min"}, set()),
    GuidelineCheck.LOWER_NOT_SMALLER: (set(), set()),
    GuidelineCheck.SYMMETRY: ({"tol_m"}, set()),
}


# ——— замер на наборе домов ———

class Measured(BaseModel):
    """Правило на наборе домов: к скольким применимо, сколько выполняют целиком, доля случаев."""

    houses: int
    passed: int
    cases: int
    share: float | None


def measure(g: Guideline, samples: list[Sample]) -> Measured:
    per_house = [cases(g, s.sheet, s.plan) for s in samples]
    applied = [c for c in per_house if c]
    flat = [ok for c in applied for ok in c]
    return Measured(houses=len(applied), passed=sum(all(c) for c in applied), cases=len(flat),
                    share=mean(flat) if flat else None)


def run(cfg: Config, out: Path) -> Path:
    """Все правила свода на домах реального теста → таблица для чтения (`genfacade guidelines`)."""
    root = cfg.data.paths.samples_dir
    samples = [store.read(root, Source.MANUAL, i) for i in store.ids(root, Source.MANUAL)]
    rows = [(g, measure(g, samples)) for g in cfg.guidelines.guideline]
    out.write_text(table(rows, len(samples)))
    return out


HEAD = """# Свод правил фасада

Собирается командой `genfacade guidelines` из `genfacade/config/guidelines.toml` — правки только
там (gf#209). Замер — на {n} домах реального теста (ручная разметка): «домов» — выполняют правило
целиком из тех, к которым оно применимо; «случаев» — доля выполненных окон, проёмов, стен, этажей.
Цитаты — дословно; [проверено] — найдена в тексте источника, тексты — `tmp/facade-rules/` (вне git).

| Правило | Проверка | Где | Домов | Случаев | Включено | Источники |
|---|---|---|---|---|---|---|
"""


def table(rows: list[tuple[Guideline, Measured]], n: int) -> str:
    return HEAD.format(n=n) + "".join(_row(g, m) for g, m in rows)


def _row(g: Guideline, m: Measured) -> str:
    params = ", ".join(f"{k} {v}" for k, v in g.params.items())
    check = f"`{g.check}` {params}".strip() + (f"; {g.note}" if g.note else "")
    houses = f"{m.passed}/{m.houses}" if m.houses else "—"
    share = f"{m.share:.2f}" if m.share is not None else "—"
    sources = "<br>".join(f"{s.doc}, {s.where}: «{s.quote}»"
                          + (" [проверено]" if s.checked else " [не проверено]") for s in g.source)
    cells = [f"**{g.id}** — {g.text}", check, ", ".join(g.applies), houses, share,
             ", ".join(g.use) or "—", sources]
    return "| " + " | ".join(c.replace("|", "/") for c in cells) + " |\n"
