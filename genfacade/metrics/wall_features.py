"""Признаки стены для слоя «отличим ли от настоящего» метрики правдоподобия (gf#210, gf#243).

Признак — число на стену; признак дома (группа Е списка gf#243, доля глухих стен, двери дома)
одинаков у всех его стен: стеночный c2st сравнивает стены, и дом попадает в него через каждую
свою стену; отдельный слой «дом» — 27 точек против 27 (почему так и чем платим —
docs/metrics-results.md, 31.10). Какие признаки идут в метрику — `[realism] features`
(config/metrics.toml), номер кандидата из списка gf#243 — в скобках у функции.

Нет величины на стене (одно окно, один этаж, нет зон) — ноль, как у идеально ровной стены.
"""

from collections.abc import Callable
from itertools import pairwise
from statistics import mean
from typing import NamedTuple

from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from genfacade.config import Realism
from genfacade.metrics import measures
from genfacade.schema import EPS, Element, ElementClass, FacadeSheet, SideFacade, ZoneRole

OPENINGS = (ElementClass.WINDOW, ElementClass.DOOR, ElementClass.GARAGE_DOOR)
DOORS = (ElementClass.DOOR, ElementClass.GARAGE_DOOR)
SECOND_FINISH = (ZoneRole.ACCENT, ZoneRole.BAND)


class Wall(NamedTuple):
    """Стена в доме: признак дома смотрит на соседние стены, порог — из настроек."""

    facade: SideFacade
    sheet: FacadeSheet
    cfg: Realism


def _avg(values: list[float]) -> float:
    return mean(values) if values else 0.0


def _of(f: SideFacade, kinds: tuple[ElementClass, ...]) -> list[Element]:
    return [e for e in f.elements if e.cls in kinds]


def _area(f: SideFacade, w: Wall) -> float:
    return f.side.length_m * w.sheet.spec.eaves_m


# ——— прежние 11 признаков gf#210 ———

def windows_per_m(w: Wall) -> float:
    """(8) окон на метр стены."""
    return len(measures.windows(w.facade)) / w.facade.side.length_m


def _measure(name: str) -> Callable[[Wall], float]:
    """Среднее величины стены из measures.STRUCTURE."""
    return lambda w: _avg(measures.STRUCTURE[name](w.facade, w.sheet.spec))


def glass(w: Wall) -> float:
    """Доля остекления: площадь окон к площади стены."""
    return measures.features(w.facade, w.sheet.spec)[4]


def edge_share(w: Wall) -> float:
    """(12) наименьший отступ окна от угла в долях длины стены."""
    return min(measures.edge_share(w.facade, w.sheet.spec), default=0.0)


def doors_per_m(w: Wall) -> float:
    return len(_of(w.facade, (ElementClass.DOOR,))) / w.facade.side.length_m


# ——— Б. состав стены ———

def blind_walls(w: Wall) -> float:
    """(7) дом: доля стен без проёмов."""
    fs = w.sheet.facades
    return sum(not _of(f, OPENINGS) for f in fs) / len(fs)


def opening_share(w: Wall) -> float:
    """(9) доля проёмов — окон и дверей — в площади стены."""
    return sum(e.w_m * e.h_m for e in _of(w.facade, OPENINGS)) / _area(w.facade, w)


def house_doors(w: Wall) -> float:
    """(10) дом: дверей всего."""
    return float(sum(len(_of(f, DOORS)) for f in w.sheet.facades))


def front_door(w: Wall) -> float:
    """(10) дом: на стене входа есть дверь — 1, нет или стены входа нет — 0."""
    return float(any(f.side.has_entrance and _of(f, DOORS) for f in w.sheet.facades))


def _floor_rows(f: SideFacade) -> list[list[Element]]:
    """Ряды проёмов, перекрытых по высоте, — слева направо."""
    rows: list[list[Element]] = []
    for e in sorted(_of(f, OPENINGS), key=lambda e: e.x_m):
        row = next((r for r in rows if _overlap_y(r[-1], e)), None)
        if row is None:
            rows.append([e])
        else:
            row.append(e)
    return rows


def _overlap_y(a: Element, b: Element) -> bool:
    return min(a.y_m + a.h_m, b.y_m + b.h_m) - max(a.y_m, b.y_m) > EPS


def min_pier_m(w: Wall) -> float:
    """(11) наименьший простенок между соседними по высоте проёмами, м."""
    gaps = [b.x_m - (a.x_m + a.w_m) for r in _floor_rows(w.facade) for a, b in pairwise(r)]
    return min(gaps, default=0.0)


def edge_m(w: Wall) -> float:
    """(12) наименьший отступ проёма от угла, м."""
    length = w.facade.side.length_m
    return min((min(e.x_m, length - e.x_m - e.w_m) for e in _of(w.facade, OPENINGS)),
               default=0.0)


# ——— В. порядок ———

def _sizes(ws: list[Element], tol: float) -> int:
    """Разных типоразмеров окон: размеры ближе tol по ширине и высоте — один."""
    found: list[Element] = []
    for e in ws:
        if not any(abs(e.w_m - s.w_m) <= tol and abs(e.h_m - s.h_m) <= tol for s in found):
            found.append(e)
    return len(found)


def sizes_floor(w: Wall) -> float:
    """(13) разных размеров окон на этаже стены, среднее по этажам."""
    floors = measures.by_floor(w.facade, w.sheet.spec)
    return _avg([float(_sizes(ws, w.cfg.size_tol_m)) for ws in floors])


def sizes_house(w: Wall) -> float:
    """(13) дом: разных размеров окон."""
    return float(_sizes([e for f in w.sheet.facades for e in measures.windows(f)],
                        w.cfg.size_tol_m))


def _center(e: Element) -> float:
    return e.x_m + e.w_m / 2


def axis_share(w: Wall) -> float:
    """(15) доля окон стены, у которых на другом этаже есть окно на той же оси; у стены
    в один этаж — 0."""
    floors = measures.by_floor(w.facade, w.sheet.spec)
    if len(floors) < 2:
        return 0.0
    on = [any(abs(_center(e) - _center(o)) <= w.cfg.axis_tol_m for other in floors
              if other is not ws for o in other) for ws in floors for e in ws]
    return sum(on) / len(on)


def symmetry(w: Wall) -> float:
    """(16) доля проёмов, у которых есть зеркальный двойник относительно середины стены:
    того же класса, на той же высоте и того же размера с точностью axis_tol_m."""
    es, length, tol = _of(w.facade, OPENINGS), w.facade.side.length_m, w.cfg.axis_tol_m
    if not es:
        return 0.0
    twins = [any(o.cls is e.cls and abs(length - _center(o) - _center(e)) <= tol
                 and abs(o.y_m - e.y_m) <= tol and abs(o.w_m - e.w_m) <= tol for o in es)
             for e in es]
    return sum(twins) / len(es)


def bottom_spread(w: Wall) -> float:
    """(18) разброс низа окон этажа в долях средней высоты окна, среднее по этажам."""
    out = []
    for ws in measures.by_floor(w.facade, w.sheet.spec):
        if len(ws) > 1:
            out.append((max(e.y_m for e in ws) - min(e.y_m for e in ws)) / mean(e.h_m for e in ws))
    return _avg(out)


# ——— Г. пропорции ———

def aspect(w: Wall) -> float:
    """(19) высота окна к ширине, среднее."""
    return _avg([e.h_m / e.w_m for e in measures.windows(w.facade)])


def frieze_m(w: Wall) -> float:
    """(21) от верха окна верхнего этажа стены до карниза, м, среднее."""
    floors = measures.by_floor(w.facade, w.sheet.spec)
    eaves = w.sheet.spec.eaves_m
    return _avg([eaves - e.y_m - e.h_m for e in floors[-1]]) if floors else 0.0


def height_share(w: Wall) -> float:
    """(22) высота окна к высоте его этажа, среднее."""
    spec = w.sheet.spec
    return _avg([e.h_m / spec.floor_heights_m[min(measures.floor_of(e, spec), spec.floors) - 1]
                 for e in measures.windows(w.facade)])


def plinth_share(w: Wall) -> float:
    """(23) верх зоны цоколя к высоте стены; зоны нет — 0."""
    tops = [max(y for _, y in z.shape) for z in w.facade.zones if z.role is ZoneRole.PLINTH]
    return max(tops, default=0.0) / w.sheet.spec.eaves_m


def cornice_share(w: Wall) -> float:
    """(23) доля длины стены под карнизом."""
    return _covered(_of(w.facade, (ElementClass.CORNICE,))) / w.facade.side.length_m


def _covered(es: list[Element]) -> float:
    """Длина объединения отрезков элементов по x."""
    total, end = 0.0, float("-inf")
    for e in sorted(es, key=lambda e: e.x_m):
        start = max(e.x_m, end)
        total += max(e.x_m + e.w_m - start, 0.0)
        end = max(end, e.x_m + e.w_m)
    return total


# ——— Д. отделка ———

def zones(w: Wall) -> float:
    """(24) зон отделки на стене."""
    return float(len(w.facade.zones))


def second_finish(w: Wall) -> float:
    """(24) доля стены под второй отделкой — акцентом и поясами."""
    shapes = [Polygon(z.shape) for z in w.facade.zones if z.role in SECOND_FINISH]
    return unary_union(shapes).area / _area(w.facade, w) if shapes else 0.0


def _profile(f: SideFacade, x: float, w: Wall) -> list[ZoneRole | None]:
    """Отделка у края стены снизу вверх с шагом zone_step_m: роль верхней зоны в точке."""
    step, eaves = w.cfg.zone_step_m, w.sheet.spec.eaves_m
    inside = min(max(x, EPS * 10), f.side.length_m - EPS * 10)
    out = []
    for k in range(int(eaves / step)):
        pt = Point(inside, (k + 0.5) * step)
        found = [z.role for z in f.zones if Polygon(z.shape).covers(pt)]
        out.append(found[-1] if found else None)
    return out


def corner_mismatch(w: Wall) -> float:
    """(25) дом: доля высоты углов, где отделка соседних стен не сходится (угол i+1 — левый
    край стены i и правый край стены i+1, как в validate._corners)."""
    fs, wrong = w.sheet.facades, []
    for a, b in zip(fs, fs[1:] + fs[:1], strict=True):
        left, right = _profile(a, 0.0, w), _profile(b, b.side.length_m, w)
        wrong += [p != q for p, q in zip(left, right, strict=True)]
    return _avg([float(x) for x in wrong])


def hidden_zones(w: Wall) -> float:
    """(26) доля зон второй отделки и цоколя тем же материалом, что основная зона стены:
    на чертеже их не видно."""
    main = [z.material for z in w.facade.zones if z.role is ZoneRole.MAIN]
    other = [z for z in w.facade.zones if z.role is not ZoneRole.MAIN]
    if not main or not other:
        return 0.0
    return sum(z.material == main[0] for z in other) / len(other)


# ——— Е. дом целиком ———

def _per_m(f: SideFacade) -> float:
    return len(_of(f, OPENINGS)) / f.side.length_m


def front_rich(w: Wall) -> float:
    """(27) дом: проёмов на метр стены входа минус на метр противоположной; входа нет — 0."""
    fs = w.sheet.facades
    front = next((f for f in fs if f.side.has_entrance), None)
    if front is None:
        return 0.0
    n = front.side.orientation
    back = min(fs, key=lambda f: f.side.orientation[0] * n[0] + f.side.orientation[1] * n[1])
    return _per_m(front) - _per_m(back)


def floor_lines(w: Wall) -> float:
    """(28) дом: разброс верха окон этажа по всем стенам в долях средней высоты окна,
    среднее по этажам."""
    floors: dict[int, list[Element]] = {}
    spec = w.sheet.spec
    for f in w.sheet.facades:
        for e in measures.windows(f):
            floors.setdefault(measures.floor_of(e, spec), []).append(e)
    spreads = [(max(e.y_m + e.h_m for e in ws) - min(e.y_m + e.h_m for e in ws))
               / mean(e.h_m for e in ws) for ws in floors.values() if len(ws) > 1]
    return _avg(spreads)


def end_windows(w: Wall) -> float:
    """(29) дом: окон на метр коротких стен (короче средней) к окнам на метр всех; окон нет
    или все стены равны — 0."""
    fs = w.sheet.facades
    average = mean(f.side.length_m for f in fs)
    ends = [f for f in fs if f.side.length_m < average - EPS]
    total = sum(len(measures.windows(f)) for f in fs) / sum(f.side.length_m for f in fs)
    if not ends or total <= EPS:
        return 0.0
    return sum(len(measures.windows(f)) for f in ends) / sum(f.side.length_m for f in ends) / total


def trim_mixed(w: Wall) -> float:
    """(30) дом: ставни и подоконники не у всех окон и не ни у одного. Для каждого — 2·min(s,
    1 − s), s — доля окон с ним; 0 — у всех или ни у одного, 1 — у половины; среднее двух."""
    fs = w.sheet.facades
    count = sum(len(measures.windows(f)) for f in fs)
    if not count:
        return 0.0
    out = []
    for cls in (ElementClass.SILL, ElementClass.BLIND):
        s = sum(_with(f, cls) for f in fs) / count
        out.append(2 * min(s, 1 - s))
    return mean(out)


def _with(f: SideFacade, cls: ElementClass) -> int:
    """Окон стены, у которых есть элемент cls; id окна уникален только в своей стене."""
    owners = {e.parent for e in f.elements if e.cls is cls}
    return sum(e.id in owners for e in measures.windows(f))


FEATURES: dict[str, Callable[[Wall], float]] = {
    # прежние 11 (gf#210)
    "windows_per_m": windows_per_m, "width_m": _measure("width_m"),
    "height_m": _measure("height_m"), "sill_m": _measure("sill_m"),
    "head_m": _measure("head_m"), "glass": glass, "top_spread": _measure("top_spread"),
    "axis_offset": _measure("axis_offset"), "gap_cv": _measure("gap_cv"),
    "edge_share": edge_share, "doors_per_m": doors_per_m,
    # Б — состав стены
    "blind_walls": blind_walls, "opening_share": opening_share, "house_doors": house_doors,
    "front_door": front_door, "min_pier_m": min_pier_m, "edge_m": edge_m,
    # В — порядок
    "sizes_floor": sizes_floor, "sizes_house": sizes_house, "axis_share": axis_share,
    "symmetry": symmetry, "bottom_spread": bottom_spread,
    # Г — пропорции
    "aspect": aspect, "frieze_m": frieze_m, "height_share": height_share,
    "plinth_share": plinth_share, "cornice_share": cornice_share,
    # Д — отделка
    "zones": zones, "second_finish": second_finish, "corner_mismatch": corner_mismatch,
    "hidden_zones": hidden_zones,
    # Е — дом целиком
    "front_rich": front_rich, "floor_lines": floor_lines, "end_windows": end_windows,
    "trim_mixed": trim_mixed,
}


def of_wall(w: Wall, names: list[str]) -> list[float]:
    return [FEATURES[n](w) for n in names]


def of_house(sheet: FacadeSheet, cfg: Realism) -> list[list[float]]:
    """Признаки `cfg.features` каждой стены дома."""
    return [of_wall(Wall(f, sheet, cfg), cfg.features) for f in sheet.facades]
