#!/usr/bin/env python3
"""Датчик gf#451: откуда у домов разметки свес — с чертежа или по умолчанию.

Запуск (ничего не пишет):
    python3 tools/overhang_probe.py [--markup ПАПКА]
Умолчание — markup/ (папки-источники, в них *.toml домов). Печатает: домов со свесом `drawing`
и `default` — всего и по источникам; медианы карнизного и фронтонного свеса по виду крыши среди
домов `drawing` (фронтонный не задан — равен карнизному). Поля — `genfacade.datasets.manual.Markup`;
дом без `overhang_by` — `default`.
Читает toml как есть, без разбора модели: поле `overhang_by` — `OverhangBy`.
"""

from __future__ import annotations

import argparse
import statistics
import tomllib
from collections import Counter, defaultdict
from pathlib import Path

from genfacade.datasets.manual import OverhangBy


def report(root: Path) -> str:
    by_source: dict[str, Counter] = defaultdict(Counter)
    eave: dict[str, list[float]] = defaultdict(list)
    gable: dict[str, list[float]] = defaultdict(list)
    for path in sorted(root.glob("*/*.toml")):
        mark = tomllib.loads(path.read_text(encoding="utf-8"))
        by = mark.get("overhang_by", OverhangBy.DEFAULT)
        by_source[path.parent.name][by] += 1
        if by == OverhangBy.DRAWING:
            kind, over = mark["roof_kind"], mark["overhang_m"]
            eave[kind].append(over)
            gable[kind].append(mark.get("gable_overhang_m", over))
    lines = ["Свес по источникам (drawing / default):"]
    total = Counter()
    for source, count in sorted(by_source.items()):
        total += count
        lines.append(f"  {source}: {count[OverhangBy.DRAWING]} / {count[OverhangBy.DEFAULT]}")
    lines.append(f"Всего: {total[OverhangBy.DRAWING]} / {total[OverhangBy.DEFAULT]}")
    lines.append("Медианы среди drawing, м (вид крыши: домов, карнизный, фронтонный):")
    for kind in sorted(eave):
        lines.append(f"  {kind}: {len(eave[kind])}, {statistics.median(eave[kind]):g}, "
                     f"{statistics.median(gable[kind]):g}")
    if not eave:
        lines.append("  нет домов со свесом drawing")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    here = Path(__file__).resolve().parent.parent
    ap.add_argument("--markup", type=Path, default=here / "markup")
    print(report(ap.parse_args().markup))


if __name__ == "__main__":
    main()
