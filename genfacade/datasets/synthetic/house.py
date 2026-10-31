"""Параметры синтетического дома: `HouseSpec` и характер стен, общий для всех сторон."""

import random
from dataclasses import dataclass
from enum import Enum

from genfacade.config import Config, Sizes, Synthetic, TrimWeights, Windows
from genfacade.datasets.synthetic.plan import on_grid
from genfacade.datasets.synthetic.sizes import grid
from genfacade.schema import (
    DOOR_KINDS,
    EPS,
    BuildingType,
    GuidelineCheck,
    HouseSpec,
    HouseTrim,
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

    head_m: float        # верх окон каждого этажа и двери над полом этажа
    cornice_m: float     # высота карниза
    window_h_m: float    # высота обычного окна
    narrow_h_m: float    # высота узкого окна
    wide_to_floor: bool  # большие окна — в пол
    scheme: Scheme
    wainscot_m: float    # высота нижнего пояса отделки над цоколем (для схемы WAINSCOT)
    porch: bool
    door: VariantKind | None  # вид входной двери; None — глухая


def house(rng: random.Random, cfg: Config, size: Sizes) -> tuple[HouseSpec, Look]:
    """Параметры и характер дома; высота этажа и цоколь — из профиля размеров дома."""
    syn = cfg.synthetic
    rules = syn.spec
    floors = rng.choices(range(1, len(rules.floors_weights) + 1), rules.floors_weights)[0]
    height = rng.choice(grid(size.floor_height_m, size.floor_height_step_m))  # одна на дом
    plinth = on_grid(rng, size.plinth_m, rules.grid_m)
    style = rng.choice(rules.styles)
    spec = HouseSpec(
        building_type=BuildingType.COTTAGE, floors=floors, floor_heights_m=[height] * floors,
        plinth_m=plinth, eaves_m=round(plinth + floors * height, 3),
        roof=Roof(kind=RoofKind.FLAT, material=PaletteRole.ROOF), style=style,
        materials=[Material(id=role, kind=kind) for role, kind in _palette(rng, syn).items()],
        trim=_trim(rng, syn.facade.trim),
    )
    return spec, _look(rng, spec, cfg)


def _trim(rng: random.Random, weights: TrimWeights) -> HouseTrim:
    """Виды выводимых элементов дома: подоконник, наличник, ставни, козырёк (gf#212)."""
    return HouseTrim(**{name: _weighted(rng, w) for name, w in weights})


def _palette(rng: random.Random, cfg: Synthetic) -> dict[PaletteRole, str]:
    """Отделка разных ролей — из разных видов, пока их хватает: иначе цоколь или акцент
    сливаются с основной стеной."""
    kinds: dict[PaletteRole, str] = {}
    for role, choice in cfg.spec.palette.items():
        fresh = [k for k in choice if k not in kinds.values()]
        kinds[role] = rng.choice(fresh or choice)
    return kinds


def _look(rng: random.Random, spec: HouseSpec, cfg: Config) -> Look:
    syn = cfg.synthetic
    windows, finish, entry = syn.facade.windows, syn.facade.finish, syn.facade.entry
    head, cornice = _head(on_grid(rng, windows.head_m, syn.spec.grid_m), spec, cfg)
    return Look(
        head_m=head,
        cornice_m=cornice,
        window_h_m=rng.choice(_heights(head, windows)),
        narrow_h_m=rng.choice(windows.narrow_heights_m),
        wide_to_floor=rng.random() < windows.wide_floor_p,
        scheme=Scheme(_weighted(rng, finish.weights)),
        wainscot_m=on_grid(rng, finish.wainscot_m, syn.spec.grid_m),
        porch=rng.random() < entry.porch_p,
        door=_door_kind(_weighted(rng, syn.facade.door.weights)),
    )


def _head(wanted: float, spec: HouseSpec, cfg: Config) -> tuple[float, float]:
    """Верх окон дома и высота карниза. Верх — не выше перемычки до потолка этажа; на верхнем
    этаже над окном с наличником до низа карниза — фриз из свода (window_head_to_eaves): тесно —
    карниз тоньше, до min_m, а дальше ниже верх окон (gf#212: окна упирались в карниз)."""
    syn = cfg.synthetic
    floor = spec.floor_heights_m[0]
    room = floor - cfg.derive.casing.get(spec.trim.casing, 0.0) - _frieze(cfg)
    head = round(min(wanted, floor - syn.facade.windows.lintel_m,
                     room - syn.facade.cornice.min_m), 3)
    return head, round(min(syn.facade.cornice.height_m, room - head), 3)


def _frieze(cfg: Config) -> float:
    """Фриз — наименьший зазор правила свода «окно не прижато к карнизу»."""
    rule = next(g for g in cfg.guidelines.guideline if g.check is GuidelineCheck.HEAD_TO_EAVES)
    return rule.params["min"]


def _heights(head: float, rules: Windows) -> list[float]:
    """Высоты окна из рядов, при которых подоконник под этим верхом — в пределах sill_m."""
    low, high = rules.sill_m
    return [h for h in rules.heights_m if low - EPS <= head - h <= high + EPS]


def _door_kind(key: str) -> VariantKind | None:
    """Ключ весов двери → вид; ключ не из видов двери (solid) — глухая."""
    return next((k for k in DOOR_KINDS if k == key), None)


def _weighted(rng: random.Random, weights: dict) -> str:
    return rng.choices(list(weights), list(weights.values()))[0]
