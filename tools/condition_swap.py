#!/usr/bin/env python3
"""Датчик gf#373: модель шага 4 на настоящих домах реального теста, у которых один признак условия
подменён на синтетический. Если с подменой перебор окон во фронтоне и по скату уходит — его даёт
этот признак (сдвиг условия: у синтетики обучения такого не бывает).

Запуск (на GPU — `gpu.yml job=swap`; на процессоре — больше 5 минут на дом):
    python3 tools/condition_swap.py <чекпойнт> <выход> [вариант …] [-c ПАПКА] [--mode РЕЖИМ …]
        [--limit N] [--seed N]
Листы — <выход>/<вариант>/<режим>/<дом>.json, как в `genfacade realtest`.

Варианты: base — как есть; style — стиль «classic» вместо пустого (у настоящих стиль не задан, у
синтетики пустого нет); roof_material — роль `roof` с видом metal_roof (у синтетики она у всех);
materials — все пять ролей палитры синтетики, недостающие — частыми видами; floors — высоты этажей
в пределах синтетики 2,5–3,0 м; style_materials, all — вместе.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from pathlib import Path

from genfacade import config
from genfacade.config import Config
from genfacade.metrics import calibrate
from genfacade.metrics.realtest import answers
from genfacade.schema import FacadeSheet, Material, Mode, PaletteRole, Source, Split
from genfacade.train.tokens import given_sides

STYLE = "classic"
ROLE_KINDS = {PaletteRole.MAIN: "wood", PaletteRole.PLINTH: "brick", PaletteRole.ACCENT: "siding",
              PaletteRole.TRIM: "metal", PaletteRole.ROOF: "metal_roof"}  # частые виды синтетики

Variant = Callable[[FacadeSheet, Config], FacadeSheet]


def _spec(s: FacadeSheet, **update: object) -> FacadeSheet:
    return s.model_copy(update={"spec": s.spec.model_copy(update=update)})


def style(s: FacadeSheet, _cfg: Config) -> FacadeSheet:
    return _spec(s, style=STYLE)


def roof_material(s: FacadeSheet, _cfg: Config) -> FacadeSheet:
    if any(m.id == PaletteRole.ROOF for m in s.spec.materials):
        return s
    roof = Material(id=PaletteRole.ROOF, kind=ROLE_KINDS[PaletteRole.ROOF])
    return _spec(s, materials=[*s.spec.materials, roof])


def materials(s: FacadeSheet, _cfg: Config) -> FacadeSheet:
    have = {m.id: m for m in s.spec.materials}
    return _spec(s, materials=[have.get(r) or Material(id=r, kind=k)
                               for r, k in ROLE_KINDS.items()])


def floors(s: FacadeSheet, cfg: Config) -> FacadeSheet:
    """Высоты этажей — в пределы профиля синтетики «как GenPlan» (real_share 0 — он у всех)."""
    low, high = cfg.synthetic.sizes.genplan.floor_height_m
    return _spec(s, floor_heights_m=[min(max(h, low), high) for h in s.spec.floor_heights_m])


def _chain(*steps: Variant) -> Variant:
    def run(s: FacadeSheet, cfg: Config) -> FacadeSheet:
        for step in steps:
            s = step(s, cfg)
        return s
    return run


VARIANTS: dict[str, Variant] = {
    "base": _chain(), "style": style, "roof_material": roof_material, "materials": materials,
    "floors": floors, "style_materials": _chain(style, materials),
    "all": _chain(style, materials, floors)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("checkpoint", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("variants", nargs="*", help=f"из {', '.join(VARIANTS)}; нет — все")
    ap.add_argument("-c", "--config", type=Path, action="append", default=[])
    ap.add_argument("--mode", type=Mode, action="append", help="нет — все режимы")
    ap.add_argument("--limit", type=int, default=0, help="первых домов; 0 — все")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    unknown = set(args.variants) - set(VARIANTS)
    if unknown:
        ap.error(f"нет вариантов {sorted(unknown)}")
    cfg = config.load(*args.config)
    layout = cfg.models.layout.model_copy(update={"checkpoint": args.checkpoint, "seed": args.seed})
    cfg = cfg.model_copy(update={"models": cfg.models.model_copy(update={"layout": layout})})
    real = calibrate.houses(Source.MANUAL, Split.TEST, 0, cfg)
    names = sorted(real)[: args.limit or None]
    if not names:
        raise SystemExit("нет настоящих домов реального теста: samples_dir без manual/")
    for mode in args.mode or Mode:
        for v in args.variants or VARIANTS:
            start = time.time()
            given = {n: given_sides(VARIANTS[v](real[n], cfg), mode) for n in names}
            answers(given, mode, cfg, args.out / v / mode.value)
            print(f"{mode.value} {v}: {len(names)} домов, {time.time() - start:.0f} с", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
