#!/usr/bin/env python3
"""Датчик gf#453: домов разметки, у которых окон выше карниза в 3D меньше, чем на листе.

Запуск (ничего не пишет): python3 tools/gable_windows_probe.py [--manual ПАПКА]
Умолчание — data/samples/manual. «На листе» — окна выше карниза на стенах с фронтоном
(`roof.sheet_gables`, `roof.over_eaves`); «в 3D» — `house_3d(...)["roof"]["windows"]`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from genfacade import roof
from genfacade.config import load
from genfacade.render.house3d import house_3d
from genfacade.schema import FacadeSheet

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manual", type=Path, default=ROOT / "data/samples/manual")
    cfg, lost, total = load(), [], 0
    for p in sorted(ap.parse_args().manual.glob("*.json")):
        data = json.loads(p.read_text())
        if p.name.startswith("_") or "sheet" not in data:
            continue
        sheet = FacadeSheet.model_validate(data["sheet"])
        total += 1
        seen = len(house_3d(sheet, cfg)["roof"].get("windows", []))
        if seen < len(roof.gable_windows(sheet)):
            lost.append(f"{p.stem}: лист {len(roof.gable_windows(sheet))}, 3D {seen}")
    print(f"домов {total}, окон выше карниза в 3D меньше, чем на листе, — {len(lost)}")
    print(*lost, sep="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
