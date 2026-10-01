"""Параметры синтетического дома: `HouseSpec` и характер стен, общий для всех сторон."""

import random
from dataclasses import dataclass

from genfacade.config import Range, Synthetic
from genfacade.datasets.synthetic.plan import on_grid
from genfacade.schema import BuildingType, HouseSpec, Material, PaletteRole, Roof, RoofKind


@dataclass(frozen=True)
class Look:
    """Чего нет в HouseSpec, но у дома одно на все стены (generation.md, п. 3)."""

    window_span: Range  # низ и верх окна в долях высоты этажа
    casing: bool        # наличники у окон
    accent: bool        # акцентная полоса отделки у входа


def house(rng: random.Random, cfg: Synthetic) -> tuple[HouseSpec, Look]:
    rules, windows = cfg.spec, cfg.facade.windows
    height = rng.choice(rules.floor_heights_m)
    plinth = on_grid(rng, rules.plinth_m, rules.grid_m)
    style = rng.choice(rules.styles)
    level = rng.choices(list(windows.weights), list(windows.weights.values()))[0]
    kinds: dict[PaletteRole, str] = {}
    for role, choice in rules.palette.items():
        # Отделка разных ролей — из разных видов, пока их хватает: иначе цоколь или акцент
        # сливаются с основной стеной.
        fresh = [k for k in choice if k not in kinds.values()]
        kinds[role] = rng.choice(fresh or choice)
    spec = HouseSpec(
        building_type=BuildingType.COTTAGE, floors=1, floor_heights_m=[height],
        plinth_m=plinth, eaves_m=round(plinth + height, 3),
        roof=Roof(kind=RoofKind.FLAT, material=PaletteRole.ROOF), style=style,
        materials=[Material(id=role, kind=kind) for role, kind in kinds.items()],
    )
    return spec, Look(windows.size[level], style in cfg.facade.casing.styles,
                      rng.random() < cfg.facade.accent.p)
