#!/usr/bin/env python3
"""Датчик gf#431, ablation крыши частей: насколько вид крыши крыла угадывают три способа.

Запуск (ничего не пишет):
    python3 tools/part_roofs_probe.py [--manual ПАПКА]
Умолчание — data/samples/manual (настоящие дома из разметки).

Крылья — все, кроме главного, у домов с двускатной или вальмовой крышей: у них пристройка под
односкатной отличима от крыши дома. Ответ по разметке — у крыла своя односкатная или крыша дома.
Способы:
- крыша дома — у всех частей крыша дома (как до gf#431);
- правило — `part_roofs.annex_roofs`: крыло ниже главного на его общей стене — односкатная;
- порог — одна граница по одному признаку крыла (доля площади главного, на сколько карниз ниже,
  глубина к длине общей стены, общая стена к длине главного), выученная по остальным домам
  (исключение по дому), среди крыльев на общей стене с главным.
С `--synthetic N` — то же по синтетике, сборка seed 0…N-1: сколько крыльев со своей односкатной
крышей и сколько из них ниже главного по карнизу (у настоящих домов — все, решение 108).
Направление — у скольких односкатных пристроек разметки низ ската от главного, как ставит правило.
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from genfacade.part_roofs import annex_roofs, away, wing_eaves
from genfacade.parts import main_wing
from genfacade.schema import EPS, FacadeSheet, Rect, RoofKind

ROOT = Path(__file__).resolve().parents[1]
PITCHED = (RoofKind.GABLE, RoofKind.HIP)
FEATURES = ("area", "drop", "deep", "share")


@dataclass(frozen=True)
class Wing:
    """Крыло, кроме главного: дом, ответ разметки, ответ правила и признаки для порога."""

    house: str
    shed: bool            # по разметке — своя односкатная
    rule: bool            # по правилу — односкатная
    down_away: bool       # низ ската по разметке — от главного
    attached: bool        # стоит на главном общей стеной
    area: float
    drop: float
    deep: float
    share: float


def _span(r: Rect) -> tuple[float, float]:
    return r.x1_m - r.x0_m, r.y1_m - r.y0_m


def _features(main: Rect, w: Rect, drop: float) -> dict[str, float]:
    """Признаки крыла: доля площади, перепад карниза, глубина / общая стена, общая / главное."""
    (mx, my), (wx, wy) = _span(main), _span(w)
    side = away(main, w)
    along_x = side is not None and side.value.endswith("x")
    shared = (wy if along_x else min(wx, mx)) if side is not None else 0.0
    depth = (wx if along_x else wy) if side is not None else 0.0
    return {"area": wx * wy / (mx * my), "drop": drop,
            "deep": depth / shared if shared > EPS else 0.0, "share": shared / max(mx, my)}


def wings(name: str, sheet: FacadeSheet, pitch: float) -> list[Wing]:
    """Крылья дома, кроме главного; дом без крыльев или с плоской / односкатной крышей — []."""
    if sheet.spec.roof.kind not in PITCHED or len(sheet.wings) < 2:
        return []
    home, rects = sheet.spec.roof, sheet.wings
    main, eaves = main_wing(rects), wing_eaves(sheet)
    told = sheet.roofs or [home] * len(rects)
    guess = annex_roofs(sheet.model_copy(update={"roofs": []}), pitch)
    out = []
    for i, w in enumerate(rects):
        if i == main:
            continue
        side = away(rects[main], w)
        out.append(Wing(name, told[i].kind is RoofKind.SHED, guess[i] is not home,
                        told[i].down_to is side and side is not None, side is not None,
                        **_features(rects[main], w, eaves[main] - eaves[i])))
    return out


def stump(train: list[Wing]) -> Callable[[Wing], bool]:
    """Лучшая на train граница «признак ≤ v» или «≥ v» среди крыльев на главном."""
    best, rule = -1, lambda _w: False
    for f in FEATURES:
        for v in _cuts([getattr(w, f) for w in train]):
            for sign in (1, -1):
                def guess(w: Wing, f=f, v=v, s=sign) -> bool:
                    return w.attached and s * (getattr(w, f) - v) <= 0
                hits = sum(guess(w) == w.shed for w in train)
                if hits > best:
                    best, rule = hits, guess
    return rule


def _cuts(values: list[float]) -> list[float]:
    """Границы — посередине между соседними значениями: значение на границе само решает класс."""
    seen = sorted(set(values))
    return [(a + b) / 2 for a, b in itertools.pairwise(seen)] or seen


def held_out(found: list[Wing]) -> int:
    """Угадано порогом при исключении по дому: граница учится без крыльев своего дома."""
    hits = 0
    for house in {w.house for w in found}:
        rule = stump([w for w in found if w.house != house])
        hits += sum(rule(w) == w.shed for w in found if w.house == house)
    return hits


def read(folder: Path) -> list[tuple[str, FacadeSheet]]:
    out = []
    for p in sorted(folder.glob("*.json")):
        data = json.loads(p.read_text())
        if not p.name.startswith("_") and "sheet" in data:
            out.append((p.stem, FacadeSheet.model_validate(data["sheet"])))
    return out


def synthetic_wings(count: int) -> list[Wing]:
    """Крылья скатных домов синтетики seed 0…count-1: настоящая сборка `build.sample`."""
    from genfacade.config import load
    from genfacade.datasets.synthetic import build

    cfg = load()
    pitch = cfg.plan.parts.annex_pitch_deg
    return [w for seed in range(count)
            for w in wings(str(seed), build.sample(seed, cfg).sheet, pitch)]


def own_roof_share(found: list[Wing]) -> str:
    """Строка о крыльях со своей односкатной крышей: сколько и какая доля ниже главного."""
    sheds = [w for w in found if w.shed]
    lower = [w for w in sheds if w.drop > EPS]
    share = len(lower) / len(sheds) if sheds else 0.0
    return (f"своя односкатная у {len(sheds)} из {len(found)} крыльев, из них ниже главного "
            f"по карнизу — {len(lower)} ({share:.2f}); крыльев ниже главного всего — "
            f"{sum(w.drop > EPS for w in found)}")


def main() -> int:
    from genfacade.config import load

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manual", type=Path, default=ROOT / "data/samples/manual")
    ap.add_argument("--synthetic", type=int, default=0, metavar="N")
    args = ap.parse_args()
    if args.synthetic:
        print("синтетика:", own_roof_share(synthetic_wings(args.synthetic)))
    pitch = load().plan.parts.annex_pitch_deg
    found = [w for name, s in read(args.manual) for w in wings(name, s, pitch)]
    sheds = [w for w in found if w.shed]
    print(f"крыльев {len(found)} в {len({w.house for w in found})} домах, "
          f"из них своя односкатная — {len(sheds)}")
    print("| способ | угадан вид крыши крыла |\n|---|---|")
    print(f"| крыша дома | {sum(not w.shed for w in found)} из {len(found)} |")
    print(f"| правило | {sum(w.rule == w.shed for w in found)} из {len(found)} |")
    print(f"| порог (исключение по дому) | {held_out(found)} из {len(found)} |")
    print(f"направление: низ от главного у {sum(w.down_away for w in sheds)} из {len(sheds)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
