"""Пример датасета по seed: план → препроцессор → параметры дома → раскладка стен."""

import random

from genfacade import pipeline
from genfacade.config import Config, Synthetic
from genfacade.datasets import genplan_writer
from genfacade.datasets.synthetic import decor, openings, plan, zones
from genfacade.datasets.synthetic.house import Look, house
from genfacade.plan.preprocess import preprocess
from genfacade.schema import FacadeSheet, HouseSpec, Mode, Sample, SideFacade, Source, Split


def sample(seed: int, cfg: Config) -> Sample:
    rules = cfg.synthetic
    svg = genplan_writer.svg(plan.draft(seed, rules), rules.canvas)
    floor = preprocess(svg, Mode.WITH_OPENINGS, cfg.plan).model_copy(
        update={"source": Source.SYNTHETIC})
    # Свой поток случайных чисел: правка правил плана не меняет параметры дома, и наоборот.
    spec, look = house(random.Random(f"house/{seed}"), rules)  # noqa: S311 — не криптография
    return Sample(id=f"rect-{seed:06d}", source=Source.SYNTHETIC, split=Split.TRAIN, plan=floor,
                  sheet=lay_out(pipeline.walls(spec, floor), look, rules))


def lay_out(sheet: FacadeSheet, look: Look, rules: Synthetic) -> FacadeSheet:
    """Раскладка всех стен дома при одних параметрах и одном характере."""
    walls = [_wall(f, sheet.spec, look, rules) for f in sheet.facades]
    return sheet.model_copy(update={"facades": walls})


def _wall(wall: SideFacade, spec: HouseSpec, look: Look, rules: Synthetic) -> SideFacade:
    cfg, side = rules.facade, wall.side
    doors = openings.doors(side, spec, cfg)
    windows = openings.windows(side, spec, look, cfg.windows)
    # порядок — порядок отрисовки: наличник под окном, подоконник и карниз поверх стены
    elements = [
        *(decor.casings(windows, cfg) if look.casing else []), *windows, *doors,
        *decor.sills(windows, cfg),
        *([decor.porch(d, spec, cfg) for d in doors] if look.porch else []),
        *([decor.canopy(d, cfg) for d in doors] if look.canopy else []),
        decor.cornice(side.length_m, spec, cfg),
    ]
    laid = wall.model_copy(update={"elements": elements})
    return laid.model_copy(update={"zones": zones.zones(laid, spec, look, cfg.finish)})
