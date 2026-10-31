"""Пример датасета по seed: план → препроцессор → параметры дома → раскладка стен."""

import random

from genfacade import pipeline
from genfacade.config import Config, Synthetic
from genfacade.datasets import genplan_writer
from genfacade.datasets.synthetic import decor, openings, plan, sizes, upper, zones
from genfacade.datasets.synthetic.house import Look, house
from genfacade.plan.preprocess import preprocess
from genfacade.schema import FacadeSheet, HouseSpec, Mode, Sample, SideFacade, Source, Split


def sample_id(seed: int) -> str:
    return f"rect-{seed:06d}"


def split(seed: int, rules: Synthetic) -> Split:
    """Часть датасета — по seed, а не по порядку сборки: дом всегда в одной и той же части."""
    draw = random.Random(f"split/{seed}").random()  # noqa: S311 — не криптография
    return Split.VAL if draw < rules.build.val_share else Split.TRAIN


def sample(seed: int, cfg: Config) -> Sample:
    rules = cfg.synthetic
    svg = genplan_writer.svg(plan.draft(seed, rules), rules.canvas)
    floor = preprocess(svg, Mode.WITH_OPENINGS, cfg.plan).model_copy(
        update={"source": Source.SYNTHETIC})
    # Свой поток случайных чисел: правка правил плана не меняет параметры дома, и наоборот.
    spec, look = house(random.Random(f"house/{seed}"), rules,  # noqa: S311 — не криптография
                       sizes.pick(seed, rules))
    sheet = lay_out(pipeline.walls(spec, floor), look, cfg,
                    random.Random(f"upper/{seed}"))  # noqa: S311 — не криптография
    return Sample(id=sample_id(seed), source=Source.SYNTHETIC, split=split(seed, rules),
                  plan=floor, sheet=sheet)


def lay_out(sheet: FacadeSheet, look: Look, cfg: Config, rng: random.Random) -> FacadeSheet:
    """Раскладка всех стен дома при одних параметрах и одном характере; rng — окна верхних
    этажей, которых нет в плане."""
    spec, rules = sheet.spec, cfg.synthetic
    walls = []
    for f in sheet.facades:
        rows = upper.rows(rng, f.side, spec.floors, cfg)
        placed = f.model_copy(update={"elements": openings.windows(rows, spec, look,
                                                                   rules.facade.windows)})
        walls.append(_wall(placed, spec, look, rules))
    return sheet.model_copy(update={"facades": walls})


def _wall(wall: SideFacade, spec: HouseSpec, look: Look, rules: Synthetic) -> SideFacade:
    """Стена с уже поставленными окнами (`wall.elements`) — дверь, декор и зоны."""
    cfg, side, windows = rules.facade, wall.side, wall.elements
    doors = openings.doors(side, spec, look, cfg)
    casing = cfg.casing.width_m if look.casing else 0.0  # ставни — снаружи наличника
    # порядок — порядок отрисовки: наличник под окном, подоконник и карниз поверх стены
    elements = [
        *(decor.casings(windows, cfg) if look.casing else []), *windows, *doors,
        *decor.sills(windows, cfg),
        *(decor.shutters(windows + doors, side.length_m, casing, cfg.shutter)
          if look.shutters else []),
        *([decor.porch(d, spec, cfg) for d in doors] if look.porch and spec.plinth_m > 0 else []),
        *([decor.canopy(d, cfg) for d in doors] if look.canopy else []),
        decor.cornice(side.length_m, spec, cfg),
    ]
    laid = wall.model_copy(update={"elements": elements})
    return laid.model_copy(update={"zones": zones.zones(laid, spec, look, cfg.finish)})
