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
from genfacade.plan.wings import SNAP, edge_runs, wings
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
    Refusal,
    Refused,
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
    main = main_wing(plan.wings)
    below = spec.wing_floors if spec.wing_floors is not None else (
        spec.floors - (rule.drop_floors if rule else 0))
    out = []
    for k, w in enumerate(plan.wings):
        lower = k != main and _minor(w, sizes[main], rule)
        out.append(level(spec, max(1, min(below, spec.floors)) if lower else spec.floors))
    return out


def main_wing(wings: list[Rect]) -> int:
    """Номер главного крыла — наибольшего по площади (первого из равных); без крыльев — 0."""
    sizes = [_area(w) for w in wings]
    return sizes.index(max(sizes)) if sizes else 0


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


class Span(NamedTuple):
    """Участок стороны на крыле: [x0, x1] вдоль стороны слева направо снаружи, номер крыла."""

    x0: float
    x1: float
    part: int


def side_spans(index: int, length: float, a: Point, b: Point, wings: list[Rect]) -> list[Span]:
    """Крылья вдоль стороны ab слева направо снаружи (x = длина − t); они должны покрыть сторону
    без щелей, границы соседних участков — одно число. Высоты не знает: нужна и дому из частей
    разной высоты (`side_runs`), и дому одной высоты (крыша по крыльям, `roof._wing_house`)."""
    along = edge_runs(a, b, wings)  # по возрастанию t от начала стороны
    starts = [0.0, *(t1 for _, _, t1 in along)]
    whole = bool(along) and all(abs(t0 - end) <= EPS for (_, t0, _), end in zip(
        along, starts, strict=False)) and abs(starts[-1] - length) <= EPS
    if not whole:
        raise ValueError(f"части дома не покрывают сторону {index}: {along}")
    ordered = list(reversed(along))
    xs = [0.0, *(length - t0 for _, t0, _ in ordered)]
    return [Span(x0 + 0.0, x1, k) for (k, _, _), x0, x1 in zip(ordered, xs[:-1], xs[1:],
                                                            strict=True)]


def side_runs(index: int, length: float, a: Point, b: Point, wings: list[Rect],
              found: list[Level]) -> list[WallRun]:
    """Участки стороны ab по частям с их этажностью и карнизом (`side_spans`)."""
    return [WallRun(x0_m=s.x0, x1_m=s.x1, part=s.part, floors=found[s.part].floors,
                    eaves_m=found[s.part].eaves_m)
            for s in side_spans(index, length, a, b, wings)]


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


def sheet_wings(plan: Plan) -> list[Rect]:
    """Крылья плана в координатах углов листа: сторона 0 листа начинается в (0, 0), а в плане — в
    первой вершине контура; сдвиг и есть разница (gf#322)."""
    ox, oy = plan.outline[0]

    def moved(v: float, origin: float) -> float:
        return round(v - origin, SNAP) + 0.0  # как округляет `wings`: без хвостов float в листе

    return [Rect(x0_m=moved(w.x0_m, ox), y0_m=moved(w.y0_m, oy),
                 x1_m=moved(w.x1_m, ox), y1_m=moved(w.y1_m, oy)) for w in plan.wings]


class StaleParts(Refused):
    """Номера частей в участках листа не сходятся с крыльями: лист собран другим разбиением."""

    def __init__(self, detail: str):
        super().__init__(Refusal.SHEET_PARTS_STALE, detail)


def _show(runs: list[tuple[int, float, float]]) -> list[tuple[int, float, float]]:
    return [(part, round(x0, 2), round(x1, 2)) for part, x0, x1 in runs]


def parts_of(sheet: FacadeSheet, corners: list[Point]) -> list[Rect]:
    """Крылья листа. Хранимые `sheet.wings` — как есть; у листа без них (собран до того,
    как лист стал их хранить) — разбиение контура, но только если участки сторон на нём ложатся:
    те же номера и границы. Иначе отказ `StaleParts`, а не чужая крыша под чужими номерами."""
    if sheet.wings:
        return sheet.wings
    rects = wings(corners)
    for k, f in enumerate(sheet.facades if stepped(sheet) else []):  # без участков сверять нечего
        length = f.side.length_m
        want = sorted((part, length - t1, length - t0) for part, t0, t1 in edge_runs(
            corners[k], corners[(k + 1) % len(corners)], rects))
        have = sorted((r.part, r.x0_m, r.x1_m) for r in f.runs)
        if len(want) != len(have) or any(
                a[0] != b[0] or abs(a[1] - b[1]) > EPS or abs(a[2] - b[2]) > EPS
                for a, b in zip(want, have, strict=True)):
            raise StaleParts(f"сторона {k}: у листа участки по частям {_show(have)}, а крылья "
                             f"контура сегодня дают {_show(want)}")
    return rects


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
    """Плоская кровля дома объёмом (gf#322): плита над каждой частью на её
    карнизе. Крылья — из листа (`parts_of`), в координатах углов дома."""
    eaves = {r.part: r.eaves_m for f in sheet.facades for r in f.runs}
    return [([(w.x0_m, w.y0_m), (w.x1_m, w.y0_m), (w.x1_m, w.y1_m), (w.x0_m, w.y1_m)], eaves[k])
            for k, w in enumerate(parts_of(sheet, corners))]
