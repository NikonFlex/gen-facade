"""Параметры синтетического дома: `HouseSpec` и характер стен, общий для всех сторон."""

import random
from dataclasses import dataclass
from enum import Enum

from genfacade.config import Range, Sizes, Synthetic
from genfacade.datasets.synthetic.plan import on_grid
from genfacade.datasets.synthetic.sizes import grid
from genfacade.schema import (
    DOOR_KINDS,
    BuildingType,
    HouseSpec,
    Material,
    PaletteRole,
    Roof,
    RoofKind,
    VariantKind,
)


class Scheme(Enum):
    """Схема отделки стен дома (ключи весов — config/synthetic.toml, [facade.finish])."""

    PLAIN = "plain"
    ENTRANCE = "entrance"
    WAINSCOT = "wainscot"
    CORNERS = "corners"
    PIERS = "piers"


@dataclass(frozen=True)
class Look:
    """Чего нет в HouseSpec, но у дома одно на все стены (`generation: Условие модели шага 4`)."""

    window_span: Range   # низ и верх обычного окна в долях высоты этажа
    wide_to_floor: bool  # большие окна — в пол
    casing: bool         # наличники у окон
    scheme: Scheme
    wainscot_m: float    # высота нижнего пояса отделки над цоколем (для схемы WAINSCOT)
    porch: bool
    canopy: bool
    door: VariantKind | None  # вид входной двери; None — глухая


def house(rng: random.Random, cfg: Synthetic, size: Sizes) -> tuple[HouseSpec, Look]:
    """Параметры и характер дома; высота этажа и цоколь — из профиля размеров дома."""
    rules = cfg.spec
    floors = rng.choices(range(1, len(rules.floors_weights) + 1), rules.floors_weights)[0]
    height = rng.choice(grid(size.floor_height_m, size.floor_height_step_m))  # одна на дом
    plinth = on_grid(rng, size.plinth_m, rules.grid_m)
    style = rng.choice(rules.styles)
    spec = HouseSpec(
        building_type=BuildingType.COTTAGE, floors=floors, floor_heights_m=[height] * floors,
        plinth_m=plinth, eaves_m=round(plinth + floors * height, 3),
        roof=Roof(kind=RoofKind.FLAT, material=PaletteRole.ROOF), style=style,
        materials=[Material(id=role, kind=kind) for role, kind in _palette(rng, cfg).items()],
    )
    return spec, _look(rng, style, cfg)


def _palette(rng: random.Random, cfg: Synthetic) -> dict[PaletteRole, str]:
    """Отделка разных ролей — из разных видов, пока их хватает: иначе цоколь или акцент
    сливаются с основной стеной."""
    kinds: dict[PaletteRole, str] = {}
    for role, choice in cfg.spec.palette.items():
        fresh = [k for k in choice if k not in kinds.values()]
        kinds[role] = rng.choice(fresh or choice)
    return kinds


def _look(rng: random.Random, style: str, cfg: Synthetic) -> Look:
    windows, finish, entry = cfg.facade.windows, cfg.facade.finish, cfg.facade.entry
    level = _weighted(rng, windows.weights)
    return Look(
        window_span=windows.size[level],
        wide_to_floor=rng.random() < windows.wide_floor_p,
        casing=style in cfg.facade.casing.styles,
        scheme=Scheme(_weighted(rng, finish.weights)),
        wainscot_m=on_grid(rng, finish.wainscot_m, cfg.spec.grid_m),
        porch=rng.random() < entry.porch_p,
        canopy=rng.random() < entry.canopy_p,
        door=_door_kind(_weighted(rng, cfg.facade.door.weights)),
    )


def _door_kind(key: str) -> VariantKind | None:
    """Ключ весов двери → вид; ключ не из видов двери (solid) — глухая."""
    return next((k for k in DOOR_KINDS if k == key), None)


def _weighted(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), list(weights.values()))[0]
