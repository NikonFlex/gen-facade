#!/usr/bin/env python3
"""Датчик gf#403: распределения разброса выравнивания и шага окон по настоящим домам.

Запуск (одной командой, ничего не пишет, таблица Markdown в stdout):
    python3 tools/tolerance_probe.py [--source manual --source buildingnet] [--config ПАПКА]
По умолчанию — реальный тест `manual` (49 домов) и BuildingNet (все части, 618 домов); процентили
и «выбираемый» — в `config/metrics.toml`, `[tolerances]`. Допуски выставляет человек по столбцу
«предварительно»: датчик не выносит pass/fail (`docs/agents/code.md`, «Сначала прибор»).

Как группируем без порога по расстоянию (порогов, которые мы калибруем, в группировке нет):
- «ряд» — окна одной стены с одним номером этажа в одном участке стены (`runs`, gf#322); сам
  номер этажа — разметки источника. Мера — размах (макс − мин) по ряду от двух окон: это то, что
  `validate._floor_align` сравнивает попарно, наибольшая пара ряда и есть размах;
- «ось» — окна одной стены на соседних этажах. Окну этажа k ищется ближайшее по центру окно
  этажа k+1 среди тех, чьи интервалы по x пересекаются; пара берётся, если ближайшие друг
  другу взаимно. Мера — расстояние левых, правых краёв и центров пары;
- «шаг» — в ряду от трёх окон просветы между соседними окнами по x; мера — размах просветов;
- «линия этажа» — медиана верха окон этажа по всему дому (стены вместе, как у `levels.py`,
  gf#275); мера — отклонение верха окна от неё.
Не мерится: сетка `tokens.grid_m` (шаг записи токенов, не свойство дома).
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from genfacade import config  # noqa: E402
from genfacade.config import Config  # noqa: E402
from genfacade.datasets import store  # noqa: E402
from genfacade.schema import ElementClass, FacadeSheet, SideFacade, Source  # noqa: E402

SOURCES = (Source.MANUAL, Source.BUILDINGNET)
MEASURES = {
    "top_range": "размах верха окон ряда, м",
    "bottom_range": "размах низа окон ряда, м",
    "gap_range": "размах просветов между окнами ряда, м",
    "axis_left": "левый край, окна одной оси на соседних этажах, м",
    "axis_right": "правый край, окна одной оси на соседних этажах, м",
    "axis_center": "центр, окна одной оси на соседних этажах, м",
    "line_jump": "верх окна от линии этажа дома, м",
}


@dataclass
class Measured:
    """Меры одного источника: имя меры → список значений по рядам, парам или окнам."""

    houses: int = 0
    values: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))


def _windows(f: SideFacade) -> list:
    return [e for e in f.elements if e.cls is ElementClass.WINDOW]


def _run(f: SideFacade, x: float) -> int | None:
    return next((j for j, r in enumerate(f.runs) if r.x0_m <= x <= r.x1_m), None)


def rows(f: SideFacade) -> list[list]:
    """Ряды стены: окна одного этажа в одном участке, по x."""
    by: dict[tuple, list] = defaultdict(list)
    for w in _windows(f):
        by[(w.floor, _run(f, w.x_m + w.w_m / 2))].append(w)
    return [sorted(r, key=lambda w: w.x_m) for r in by.values()]


def row_measures(row: list) -> dict[str, float]:
    """Размахи верха, низа и просветов одного ряда (меры, которых у ряда нет, пропускаются)."""
    out = {}
    if len(row) >= 2:
        tops, bottoms = [w.y_m + w.h_m for w in row], [w.y_m for w in row]
        out = {"top_range": max(tops) - min(tops), "bottom_range": max(bottoms) - min(bottoms)}
    if len(row) >= 3:
        gaps = [b.x_m - (a.x_m + a.w_m) for a, b in zip(row, row[1:], strict=False)]
        if all(g > 0 for g in gaps):
            out["gap_range"] = max(gaps) - min(gaps)
    return out


def _center(w) -> float:
    return w.x_m + w.w_m / 2


def _nearest(w, others: list):
    """Ближайшее по центру окно среди тех, что перекрывают w по x; нет перекрытия — None."""
    over = [o for o in others if min(o.x_m + o.w_m, w.x_m + w.w_m) > max(o.x_m, w.x_m)]
    return min(over, key=lambda o: abs(_center(o) - _center(w)), default=None)


def axis_pairs(f: SideFacade) -> list[tuple]:
    """Пары окон одной оси на соседних этажах: ближайшие друг другу взаимно."""
    floors = defaultdict(list)
    for w in _windows(f):
        floors[w.floor].append(w)
    pairs = []
    for k, low in floors.items():
        up = floors.get(k + 1, []) if k is not None else []
        pairs += [(a, b) for a in low if (b := _nearest(a, up)) is not None
                  and _nearest(b, low) is a]
    return pairs


def measure_house(sheet: FacadeSheet, into: Measured) -> None:
    into.houses += 1
    tops: dict[int | None, list[float]] = defaultdict(list)
    for f in sheet.facades:
        for row in rows(f):
            for name, value in row_measures(row).items():
                into.values[name].append(value)
        for a, b in axis_pairs(f):
            into.values["axis_left"].append(abs(a.x_m - b.x_m))
            into.values["axis_right"].append(abs(a.x_m + a.w_m - b.x_m - b.w_m))
            into.values["axis_center"].append(abs(_center(a) - _center(b)))
        for w in _windows(f):
            tops[w.floor].append(w.y_m + w.h_m)
    for sheet_f in sheet.facades:
        for w in _windows(sheet_f):
            into.values["line_jump"].append(abs(w.y_m + w.h_m - statistics.median(tops[w.floor])))


def measure(sheets: list[FacadeSheet]) -> Measured:
    out = Measured()
    for sheet in sheets:
        measure_house(sheet, out)
    return out


def percentiles(values: list[float], qs: list[float]) -> list[float]:
    return [float(v) for v in numpy.percentile(values, qs)] if values else [float("nan")] * len(qs)


def share_within(values: list[float], tol: float) -> float:
    return float(numpy.mean([v <= tol for v in values])) if values else float("nan")


def near_axis_share(values: list[float], eps: float, tol: float) -> float:
    """Доля пар «почти на одной оси» (eps < расстояние ≤ tol) среди пар в пределах tol — то, что
    `validate._axis_align` предупреждает."""
    close = [v for v in values if v <= tol]
    return float(numpy.mean([v > eps for v in close])) if close else float("nan")


def table(name: str, m: Measured, cfg: Config) -> str:
    qs = cfg.metrics.tolerances.percentiles
    head = " | ".join(f"P{q:g}" for q in qs)
    lines = [f"### {name}: {m.houses} домов", "",
             f"| мера | n | {head} |", "|---|---|" + "---|" * len(qs)]
    for key, title in MEASURES.items():
        v = m.values.get(key, [])
        cells = " | ".join(f"{x:.3f}" for x in percentiles(v, qs))
        lines.append(f"| {title} | {len(v)} | {cells} |")
    return "\n".join(lines)


def current(m: Measured, cfg: Config) -> str:
    """Что говорят нынешние допуски настоящим домам."""
    c, pick = cfg.checks, cfg.metrics.tolerances.pick
    shares = [
        (f"ряды с верхом в пределах align_m = {c.align_m}", "top_range", c.align_m),
        (f"окна в пределах snap_m = {c.snap_m} от линии этажа", "line_jump", c.snap_m),
        (f"окна в пределах window_jump_m = {c.window_jump_m} от линии этажа", "line_jump",
         c.window_jump_m),
        (f"оси с центрами в пределах axis_tol_m = {cfg.metrics.realism.axis_tol_m}", "axis_center",
         cfg.metrics.realism.axis_tol_m)]
    lines = ["| при нынешнем допуске | доля |", "|---|---|"]
    lines += [f"| {t} | {share_within(m.values.get(k, []), tol):.1%} |" for t, k, tol in shares]
    near = near_axis_share(m.values.get("axis_center", []), c.eps_m, c.align_m)
    lines.append(f"| пары в пределах align_m, но не ровно (eps_m < d ≤ align_m): «почти на оси» "
                 f"| {near:.1%} |")
    picks = ", ".join(f"{k}: {percentiles(m.values.get(k, []), [pick])[0]:.3f}"
                      for k in MEASURES)
    return "\n".join(lines) + f"\n\nP{pick:g} по мерам: {picks}"


def houses(source: Source, cfg: Config) -> list[FacadeSheet]:
    root = cfg.data.paths.samples_dir
    return [store.read(root, source, i).sheet for i in store.ids(root, source)]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", action="append", type=Source, help="источник (по умолчанию два)")
    ap.add_argument("--config", action="append", type=Path, default=[])
    args = ap.parse_args(argv)
    cfg = config.load(*args.config)
    pooled = Measured()
    for source in args.source or SOURCES:
        m = measure(houses(source, cfg))
        print(table(str(source), m, cfg), "\n", current(m, cfg), "\n", sep="\n")
        pooled.houses += m.houses
        for k, v in m.values.items():
            pooled.values[k] += v
    if not args.source:
        print(table("вместе", pooled, cfg), "\n", current(pooled, cfg), sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
