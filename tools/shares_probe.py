#!/usr/bin/env python3
"""Датчик gf#373, gf#431: пять долей — синтетика, листы модели, настоящие дома.

Запуск (одной командой, ничего не пишет):
    python3 tools/shares_probe.py [--synthetic ПАПКА] [--manual ПАПКА] [--realtest ПАПКА]
Умолчания — data/samples/synthetic, data/samples/manual. `--realtest` — распакованный артефакт
`realtest-<run>` (`gh run download <run> -n realtest-<run>`): папки `<режим>/<строка>/*.json`.

Доли (одно определение на все источники; дом без листа — отказ модели — не считается):
- фронтон — доля скатных домов (крыша не плоская), у которых есть окно выше карниза
  (верх окна над eaves_m);
- ставни — окон с парой ставен (есть элемент `blind` с `parent` = окну) на окно, среди домов,
  у которых вид ставен не none (у остальных ставен нет по построению);
- скат — окон `slope` на 100 скатных домов (и сколько их всего);
- своя крыша части (gf#431) — доля скатных домов с двумя и более крыльями, у которых крыша хотя бы
  одной части отличается от крыши дома видом или уклоном;
- щипец над стеной (gf#431) — доля двускатных домов с непустым `wall_gables`.
У настоящих домов — интервал разброса: бутстреп по домам, 2,5–97,5 %.
"""

from __future__ import annotations

import argparse
import json
import random
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from genfacade.schema import ElementClass, FacadeSheet, RoofKind, Trim, VariantKind

ROOT = Path(__file__).resolve().parents[1]
BOOT = 2000          # перевыборок бутстрепа
BOUNDS = (0.025, 0.975)
SEED = 373
SHARES = 5           # долей в `shares`
PITCH_TOL_DEG = 0.5  # уклоны крыши части и дома, что различаются меньше, — один и тот же


@dataclass(frozen=True)
class House:
    """Что нужно датчику от одного дома."""

    roof: RoofKind
    gable: bool         # окно выше карниза
    windows: int        # окон у дома, у которого ставни есть по виду (иначе 0)
    shuttered: int      # из них с парой ставен
    slope_windows: int  # окон-трапеций по скату
    winged: bool = False     # крыльев две и больше
    own_roof: bool = False   # у части крыша другого вида или уклона, чем у дома
    wall_gable: bool = False  # есть щипец над карнизной стеной

    @property
    def sloped(self) -> bool:
        return self.roof is not RoofKind.FLAT


def has_own_roof(sheet: FacadeSheet) -> bool:
    """Крыша хотя бы одной части отличается от крыши дома видом или уклоном."""
    home = sheet.spec.roof
    return any(r.kind is not home.kind or abs(r.pitch_deg - home.pitch_deg) > PITCH_TOL_DEG
               for r in sheet.roofs)


def house(sheet: FacadeSheet) -> House:
    spec = sheet.spec
    has = spec.trim.has(Trim.SHUTTERS)
    windows = shuttered = slope = gable = 0
    for facade in sheet.facades:  # id элементов — в пределах стены
        parents = {e.parent for e in facade.elements if e.cls is ElementClass.BLIND}
        for w in (e for e in facade.elements if e.cls is ElementClass.WINDOW):
            windows += 1
            shuttered += w.id in parents
            slope += w.variant is not None and w.variant.kind is VariantKind.SLOPE
            gable += w.y_m + w.h_m > spec.eaves_m
    return House(roof=spec.roof.kind, gable=gable > 0,
                 windows=windows if has else 0, shuttered=shuttered if has else 0,
                 slope_windows=slope, winged=len(sheet.wings) >= 2,
                 own_roof=has_own_roof(sheet), wall_gable=bool(sheet.wall_gables))


def read_sheet(path: Path) -> FacadeSheet | None:
    """Лист из файла образца (поле sheet) или листа модели; отказ модели — None."""
    data = json.loads(path.read_text())
    data = data.get("sheet", data)
    return FacadeSheet.model_validate(data) if "spec" in data else None


def load(folder: Path) -> list[House]:
    sheets = (read_sheet(p) for p in sorted(folder.glob("*.json")) if not p.name.startswith("_"))
    return [house(s) for s in sheets if s is not None]


def shares(houses: list[House]) -> tuple[float, ...]:
    """(фронтон, ставен на окно, окон по скату на 100 скатных домов, своя крыша части среди
    скатных с крыльями, щипец над стеной среди двускатных)."""
    sloped = [h for h in houses if h.sloped]
    winged = [h for h in sloped if h.winged]
    two = [h for h in houses if h.roof is RoofKind.GABLE]
    windows = sum(h.windows for h in houses)
    return (sum(h.gable for h in sloped) / max(len(sloped), 1),
            sum(h.shuttered for h in houses) / max(windows, 1),
            100 * sum(h.slope_windows for h in sloped) / max(len(sloped), 1),
            sum(h.own_roof for h in winged) / max(len(winged), 1),
            sum(h.wall_gable for h in two) / max(len(two), 1))


def interval(houses: list[House]) -> list[tuple[float, float]]:
    """Интервал каждой доли: бутстреп по домам."""
    rng = random.Random(SEED)  # noqa: S311 — не криптография
    runs = [shares(rng.choices(houses, k=len(houses))) for _ in range(BOOT)]
    out = []
    for k in range(SHARES):
        values = sorted(r[k] for r in runs)
        out.append((values[int(BOUNDS[0] * BOOT)], values[int(BOUNDS[1] * BOOT) - 1]))
    return out


def gable_roofs(houses: list[House]) -> float:
    """Фронтон у домов с двускатной крышей — там его ставит генератор."""
    two = [h for h in houses if h.roof is RoofKind.GABLE]
    return sum(h.gable for h in two) / max(len(two), 1)


def span(value: str, bounds: tuple[float, float] | None, digits: int = 2) -> str:
    return value if bounds is None else f"{value} [{bounds[0]:.{digits}f}–{bounds[1]:.{digits}f}]"


def row(name: str, houses: list[House], bounds: list[tuple[float, float]] | None = None) -> str:
    gable, shutters, slope, own, wall = shares(houses)
    sloped = [h for h in houses if h.sloped]
    gabled = sum(h.roof is RoofKind.GABLE for h in houses)
    b = bounds or [None] * SHARES
    winged = sum(h.winged for h in sloped)
    slope_n = sum(h.slope_windows for h in sloped)
    cells = [span(f"{gable:.2f}", b[0]), span(f"{shutters:.2f}", b[1]),
             span(f"{slope:.1f} ({slope_n})", b[2], 1), f"{gable_roofs(houses):.2f}",
             span(f"{own:.2f} ({winged})", b[3]), span(f"{wall:.2f}", b[4])]
    return f"| {name} | {len(houses)} / {len(sloped)} / {gabled} | " + " | ".join(cells) + " |"


def sources(args: argparse.Namespace) -> Iterable[tuple[str, list[House], bool]]:
    """(название, дома, настоящие ли) — по порядку печати."""
    if args.synthetic.is_dir():
        yield "синтетика", load(args.synthetic), False
    if args.manual.is_dir():
        yield "настоящие (manual)", load(args.manual), True
    if args.realtest:
        for mode in sorted(p for p in args.realtest.iterdir() if p.is_dir()):
            for line in ("reference", "model-train", "model-finetune"):
                if (mode / line).is_dir():
                    yield f"{mode.name}: {line}", load(mode / line), line == "reference"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synthetic", type=Path, default=ROOT / "data/samples/synthetic")
    ap.add_argument("--manual", type=Path, default=ROOT / "data/samples/manual")
    ap.add_argument("--realtest", type=Path, default=None)
    args = ap.parse_args()
    print("| источник | домов / скатных / двускатных | фронтон (скатные) | ставен на окно "
          "| окон по скату на 100 скатных (всего) | фронтон (двускатные) "
          "| своя крыша части (скатных с крыльями) | щипец над стеной (двускатные) |")
    print("|---|---|---|---|---|---|---|---|")
    for name, houses, real in sources(args):
        print(row(name, houses, interval(houses) if real else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
