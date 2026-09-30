"""Шаг 5: привязка к сетке этажей и осей (generation.md, п. 7).

Окна, чьи оси ближе snap_m, встают на одну ось и одну ширину; окна одного этажа — на одну
линию низа и одну высоту. Заданное планом (`fixed`) не двигается — к нему тянутся остальные.
Подоконник и наличник едут вместе со своим окном. Правило шага 4 и так выравнивает —
привязка нужна модели, её выход неточный.
"""

from statistics import median

from genfacade.config import Checks
from genfacade.schema import EPS, Element, FacadeSheet, SideFacade


def snap(sheet: FacadeSheet, cfg: Checks) -> FacadeSheet:
    return sheet.model_copy(update={"facades": [snap_side(f, cfg) for f in sheet.facades]})


def snap_side(f: SideFacade, cfg: Checks) -> SideFacade:
    windows = [e for e in f.elements if e.cls == "window"]
    moved = {w.id: w for w in windows}
    for group in _clusters(windows, cfg.snap_m):
        x, w = _target(group)
        for e in group:
            if _differs((e.x_m, e.w_m), (x, w)):
                moved[e.id] = moved[e.id].model_copy(update={"x_m": x, "w_m": w})
    for floor in {w.floor for w in windows}:
        row = [moved[w.id] for w in windows if w.floor == floor]
        y, h = median(e.y_m for e in row), median(e.h_m for e in row)
        for e in row:
            near = abs(e.y_m - y) <= cfg.snap_m and abs(e.h_m - h) <= cfg.snap_m
            if near and _differs((e.y_m, e.h_m), (y, h)):
                moved[e.id] = e.model_copy(update={"y_m": y, "h_m": h})
    elements = [moved.get(e.id) or _follow(e, moved, f.elements) for e in f.elements]
    return f.model_copy(update={"elements": elements})


def _differs(a: tuple[float, float], b: tuple[float, float]) -> bool:
    """Двигать только то, что стоит мимо: иначе хвосты float портят точные координаты."""
    return any(abs(p - q) > EPS for p, q in zip(a, b, strict=True))


def _center(e: Element) -> float:
    return e.x_m + e.w_m / 2


def _clusters(windows: list[Element], tol: float) -> list[list[Element]]:
    """Окна по осям: соседние по центру ближе tol — в одной группе."""
    groups: list[list[Element]] = []
    for w in sorted(windows, key=_center):
        if groups and _center(w) - _center(groups[-1][-1]) <= tol:
            groups[-1].append(w)
        else:
            groups.append([w])
    return groups


def _target(group: list[Element]) -> tuple[float, float]:
    """Ось группы: у заданного планом — его (так оно и не двигается), иначе медиана.

    Двух заданных планом окон в группе не бывает: оси ближе snap_m — окна пересекались бы.
    """
    fixed = [e for e in group if "x_m" in e.fixed]
    if fixed:
        return fixed[0].x_m, fixed[0].w_m
    w = median(e.w_m for e in group)
    return median(_center(e) for e in group) - w / 2, w


def _follow(child: Element, moved: dict[str, Element], before: list[Element]) -> Element:
    """Подоконник и наличник повторяют сдвиг и растяжение окна."""
    if child.parent not in moved:
        return child
    old = next(e for e in before if e.id == child.parent)
    new = moved[child.parent]
    dx, dw, dy, dh = new.x_m - old.x_m, new.w_m - old.w_m, new.y_m - old.y_m, new.h_m - old.h_m
    # наличник обнимает окно по высоте и растягивается с ним, подоконник под окном — только едет
    stretch = child.y_m >= old.y_m - EPS
    h = child.h_m + (dh if stretch else 0.0)
    return child.model_copy(update={"x_m": child.x_m + dx, "w_m": child.w_m + dw,
                                    "y_m": child.y_m + dy, "h_m": h})
