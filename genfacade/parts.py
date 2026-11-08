"""Дом из частей разной высоты (gf#322, `facade: Части дома`).

Часть — прямоугольное крыло контура (`Plan.wings`, шаг 2) со своей этажностью и карнизом; отделка,
цоколь и стиль — общие, из HouseSpec. Шаг 3 делит каждую сторону плана на участки по частям
(`WallRun`) и рисует силуэт стены ступенями. Высота — свойство части, поэтому на выпуклом углу
высоты двух стен одной части совпадают по построению, а на стыке частей нижняя стена упирается в
более высокую.

Модель шага 4 стену из частей не видит: каждый участок — своя стена длиной с участок и с параметрами
своей части, как прямоугольный дом (`sub_sheets`); раскладки участков собирает `merge`. Так модель
остаётся той же, переобучение не нужно.

Кратчайший путь: два уровня — главная (самая большая) часть и нижние части. Крыша над частями пока
плоская (`roof.builds`).
"""

from typing import NamedTuple

from genfacade.config import Parts
from genfacade.plan.wings import edge_runs, wings
from genfacade.schema import (
    EPS,
    Element,
    FacadeSheet,
    HouseSpec,
    MaterialZone,
    Opening,
    OpeningKind,
    Plan,
    Point,
    Polygon,
    Rect,
    Roof,
    RoofKind,
    Side,
    SideFacade,
    WallRun,
)
from genfacade.unfold import unfold


class Level(NamedTuple):
    """Этажность и карниз части."""

    floors: int
    eaves_m: float


def levels(spec: HouseSpec, plan: Plan, rule: Parts | None = None) -> list[Level]:
    """Этажность и карниз каждого крыла плана. Главное — самое большое (первое из равных) — как
    у дома. Нижнее — нетолстое и небольшое крыло (rule): меньше `ratio` площади главного и не
    уже `wing_min_m`; этажей у него `spec.wing_floors`, а без него — на `drop_floors` меньше.
    Без rule нижнее — любое неглавное крыло с `wing_floors`."""
    sizes = [_area(w) for w in plan.wings]
    main = sizes.index(max(sizes)) if sizes else 0
    below = spec.wing_floors if spec.wing_floors is not None else (
        spec.floors - (rule.drop_floors if rule else 0))
    out = []
    for k, w in enumerate(plan.wings):
        lower = k != main and _minor(w, sizes[main], rule)
        out.append(level(spec, max(1, min(below, spec.floors)) if lower else spec.floors))
    return out


def level(spec: HouseSpec, floors: int) -> Level:
    """Карниз части в `floors` этажей: верх её последнего этажа и тот же запас, что у дома."""
    rise = spec.eaves_m - spec.floor_levels()[-1]
    return Level(floors, spec.floor_levels()[floors] + rise)


def _area(w: Rect) -> float:
    return (w.x1_m - w.x0_m) * (w.y1_m - w.y0_m)


def _minor(w: Rect, main_area: float, rule: Parts | None) -> bool:
    if rule is None:
        return True
    narrow = min(w.x1_m - w.x0_m, w.y1_m - w.y0_m)
    return _area(w) < rule.ratio * main_area and narrow >= rule.wing_min_m


def runs(spec: HouseSpec, plan: Plan, rule: Parts | None = None) -> list[list[WallRun]]:
    """Участки каждой стороны по частям; все пусты, если у частей одна высота — дом без ступеней."""
    return stepped_runs(plan, levels(spec, plan, rule))


def stepped_runs(plan: Plan, found: list[Level]) -> list[list[WallRun]]:
    """Участки сторон по заданным этажности и карнизу крыльев (`levels` — по правилу, разметка
    реального дома — по листу); у частей одной высоты участков нет."""
    if len({lv.eaves_m for lv in found}) <= 1:
        return [[] for _ in plan.sides]
    ring = plan.outline
    return [side_runs(s.index, s.length_m, ring[i], ring[(i + 1) % len(ring)], plan.wings, found)
            for i, s in enumerate(plan.sides)]


def side_runs(index: int, length: float, a: Point, b: Point, wings: list[Rect],
              found: list[Level]) -> list[WallRun]:
    """Участки стороны ab слева направо снаружи (x = длина − t); части должны покрыть сторону
    без щелей, границы соседних участков — одно число."""
    along = edge_runs(a, b, wings)  # по возрастанию t от начала стороны
    starts = [0.0, *(t1 for _, _, t1 in along)]
    whole = bool(along) and all(abs(t0 - end) <= EPS for (_, t0, _), end in zip(
        along, starts, strict=False)) and abs(starts[-1] - length) <= EPS
    if not whole:
        raise ValueError(f"части дома не покрывают сторону {index}: {along}")
    ordered = list(reversed(along))
    xs = [0.0, *(length - t0 for _, t0, _ in ordered)]
    return [WallRun(x0_m=x0 + 0.0, x1_m=x1, part=k, floors=found[k].floors,
                    eaves_m=found[k].eaves_m)
            for (k, _, _), x0, x1 in zip(ordered, xs[:-1], xs[1:], strict=True)]


def home_run(o: Opening, runs: list[WallRun]) -> WallRun:
    """Участок, которому принадлежит проём плана: с большей долей проёма (при равных — левый).
    Проём на границе частей не бракуется, а отдаётся одной из них."""
    share = [(min(o.x_m + o.width_m, r.x1_m) - max(o.x_m, r.x0_m), -j) for j, r in enumerate(runs)]
    return runs[-max(share)[1]]


def clamped(o: Opening, runs: list[WallRun]) -> Opening:
    """Проём плана, каким его ставит модель: у стены из частей — внутри своего участка; доля за
    границей отрезана, у стены без участков проём как в плане."""
    if not runs:
        return o
    home = home_run(o, runs)
    x0, x1 = max(o.x_m, home.x0_m), min(o.x_m + o.width_m, home.x1_m)
    return o.model_copy(update={"x_m": x0, "width_m": x1 - x0})


def stepped(sheet: FacadeSheet) -> bool:
    return any(f.runs for f in sheet.facades)


# ——— Шаг 4: участки как отдельные стены ———


class Piece(NamedTuple):
    """Участок стены: сторона k, его номер j в стороне."""

    k: int
    j: int
    run: WallRun


def pieces(sheet: FacadeSheet) -> list[Piece]:
    return [Piece(k, j, r) for k, f in enumerate(sheet.facades) for j, r in enumerate(f.runs)]


def run_spec(spec: HouseSpec, floors: int) -> HouseSpec:
    """Параметры части в `floors` этажей. Крыша плоская: скаты над участком не строятся, а на
    стороне без смысла контура roof.py спотыкался бы о незамкнутый обход."""
    flat = Roof(kind=RoofKind.FLAT, material=spec.roof.material)
    return spec.model_copy(update={
        "floors": floors, "floor_heights_m": spec.floor_heights_m[:floors], "roof": flat,
        "eaves_m": level(spec, floors).eaves_m, "wing_floors": None})


def sub_sheets(sheet: FacadeSheet) -> dict[int, tuple[FacadeSheet, list[Piece]]]:
    """Для каждой этажности частей — «дом» из её участков (стены подряд) и сами участки."""
    groups: dict[int, list[Piece]] = {}
    for p in pieces(sheet):
        groups.setdefault(p.run.floors, []).append(p)
    return {floors: (unfold(FacadeSheet(
        spec=run_spec(sheet.spec, floors),
        facades=[SideFacade(side=_run_side(sheet.facades[p.k].side, p.run,
                                           sheet.facades[p.k].runs, n))
                 for n, p in enumerate(items)])), items)
        for floors, items in groups.items()}


def _run_side(side: Side, run: WallRun, runs: list[WallRun], index: int) -> Side:
    """Сторона длиной с участок: проёмы и запретные зоны — внутри участка, x от его края; проём
    на границе частей — у части с большей долей (`home_run`), отрезанный по участку."""
    inside = [c for c in (clamped(o, runs) for o in side.openings) if c.x_m >= run.x0_m - EPS
              and c.x_m + c.width_m <= run.x1_m + EPS and home_run(c, runs) == run]
    forbidden = [z.model_copy(update={"x0_m": max(z.x0_m, run.x0_m) - run.x0_m,
                                      "x1_m": min(z.x1_m, run.x1_m) - run.x0_m})
                 for z in side.forbidden if min(z.x1_m, run.x1_m) - max(z.x0_m, run.x0_m) > EPS]
    return side.model_copy(update={
        "index": index, "length_m": run.x1_m - run.x0_m, "forbidden": forbidden,
        "openings": [o.model_copy(update={"x_m": o.x_m - run.x0_m}) for o in inside],
        "has_entrance": any(o.kind is OpeningKind.ENTRANCE for o in inside)})


def merge(sheet: FacadeSheet, answers: dict[int, FacadeSheet],
          items: dict[int, list[Piece]]) -> FacadeSheet:
    """Ответы по частям (этажность → «дом» из участков) — на стены дома: элементы и зоны участков
    сдвинуты на его x0; если участков у стороны несколько, id элементов получают номер участка."""
    elements: dict[int, list[Element]] = {}
    zones: dict[int, list[MaterialZone]] = {}
    for floors, pcs in items.items():
        for n, p in enumerate(pcs):
            wall = answers[floors].facades[n]
            many = len(sheet.facades[p.k].runs) > 1
            elements.setdefault(p.k, []).extend(_moved(e, p, many) for e in wall.elements)
            zones.setdefault(p.k, []).extend(_shifted_zone(z, p.run.x0_m) for z in wall.zones)
    facades = [f.model_copy(update={"elements": sorted(elements.get(k, []), key=_order),
                                    "zones": zones.get(k, [])})
               for k, f in enumerate(sheet.facades)]
    return sheet.model_copy(update={"facades": facades})


def _order(e: Element) -> tuple[float, str]:
    return e.x_m, e.id


def _moved(e: Element, p: Piece, many: bool) -> Element:
    prefix = f"r{p.j}_" if many else ""
    return e.model_copy(update={
        "id": prefix + e.id, "x_m": e.x_m + p.run.x0_m,
        "parent": prefix + e.parent if e.parent else None})


def _shifted_zone(z: MaterialZone, dx: float) -> MaterialZone:
    return z.model_copy(update={"shape": [(x + dx, y) for x, y in z.shape]})


def slabs(sheet: FacadeSheet, corners: list[Point]) -> list[tuple[Polygon, float]]:
    """Плоская кровля дома объёмом (gf#322): плита над каждой частью на её карнизе. Крылья берутся
    тем же разбиением контура, что на шаге 2, — по углам дома (контур тот же, сдвинут в нуль)."""
    eaves = {r.part: r.eaves_m for f in sheet.facades for r in f.runs}
    return [([(w.x0_m, w.y0_m), (w.x1_m, w.y0_m), (w.x1_m, w.y1_m), (w.x0_m, w.y1_m)], eaves[k])
            for k, w in enumerate(wings(corners))]
