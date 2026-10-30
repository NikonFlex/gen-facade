"""Пример датасета по seed: план → препроцессор → параметры дома → раскладка стен."""

import random

from genfacade import derive, pipeline
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
    spec, look = house(random.Random(f"house/{seed}"), cfg,  # noqa: S311 — не криптография
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
        walls.append(_wall(placed, spec, look, cfg))
    return sheet.model_copy(update={"facades": walls})


def _wall(wall: SideFacade, spec: HouseSpec, look: Look, cfg: Config) -> SideFacade:
    """Стена с уже поставленными окнами (`wall.elements`) — дверь, декор и зоны. Подоконники,
    наличники, ставни и козырёк правило только отмечает у проёма, ставит их код (derive.py)."""
    rules, side, windows = cfg.synthetic.facade, wall.side, wall.elements
    doors = openings.doors(side, spec, look, rules)
    porch = look.porch and spec.plinth_m > 0  # крыльцо — на высоту цоколя: без цоколя его нет
    porches = [decor.porch(d, spec, rules) for d in doors] if porch else []
    ctx = derive.Wall(spec, side.length_m, cfg.derive)
    laid = [*windows, *doors, *porches, decor.cornice(side.length_m, spec, look.cornice_m)]
    elements = derive.place(laid, decor.flags(windows, doors, ctx), ctx)
    placed = wall.model_copy(update={"elements": elements})
    return placed.model_copy(update={"zones": zones.zones(placed, spec, look, rules.finish)})
