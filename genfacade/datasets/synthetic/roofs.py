"""Составные крыши синтетики (gf#431, `facade: Крыша над частями дома`, `facade: Щипец над
карнизной стеной`): односкатная крыша пристройки и щипец над входом.

Свою односкатную крышу получает только крыло НИЖЕ главного по карнизу — как у настоящих домов
(решение 108). Синтетика делит дом на части одной высоты, поэтому дом, которому по жребию нужна
пристройка под своей крышей, строится ступенями (`annexed`): нижнее крыло — по правилу частей
(`config/plan.toml [parts]`), стены каждой части раскладываются как отдельный дом
(`build.lay_out_parts`).
Остальные дома и их жребии по seed не меняются.

Крыши и щипец ставятся ПОСЛЕ раскладки стен и со своим потоком случайных чисел: окна, зоны и условие
модели шага 4 от них не зависят (модель стену раскладывает до карниза, крыши частей не видит).
Жребий каждого решения тянется всегда, чтобы одно не сдвигало другое.
"""

import random

from genfacade import entrance_gable
from genfacade.config import Composite, Config
from genfacade.part_roofs import away, wing_eaves
from genfacade.parts import main_wing
from genfacade.schema import (
    EPS,
    FacadeSheet,
    HouseSpec,
    Plan,
    Roof,
    RoofKind,
)


def annexed(seed: int, spec: HouseSpec, plan: Plan, cfg: Config) -> bool:
    """Дому по жребию нужна пристройка под своей крышей: у скатного дома с крыльями выпал первый
    жребий потока крыш (тот же, что в `compose`) — и дом строится ступенями."""
    rules = cfg.synthetic.spec.composite
    draw = random.Random(f"roofs/{seed}").random()  # noqa: S311 — не криптография
    return spec.roof.kind is not RoofKind.FLAT and len(plan.wings) >= 2 and draw < rules.part_p


def compose(rng: random.Random, sheet: FacadeSheet, cfg: Config) -> FacadeSheet:
    """Лист с крышей пристроек и щипцом над входом — там, где они подходят дому."""
    rules = cfg.synthetic.spec.composite
    wing_draw, gable_draw = rng.random(), rng.random()
    if sheet.spec.roof.kind is RoofKind.FLAT:
        return sheet
    if len(sheet.wings) >= 2 and wing_draw < rules.part_p:
        own = part_roofs(rng, sheet, rules)
        sheet = sheet if all(r is sheet.spec.roof for r in own) else sheet.model_copy(
            update={"roofs": own})
    if sheet.spec.roof.kind is RoofKind.GABLE and gable_draw < rules.wall_gable_p:
        sheet = _with_gable(rng, sheet, rules)
    return sheet


def part_roofs(rng: random.Random, sheet: FacadeSheet, rules: Composite) -> list[Roof]:
    """Крыша каждого крыла: у пристройки, что стоит на главном крыле и ниже него по карнизу, —
    односкатная, низ ската от главного; у остальных — крыша дома."""
    house, wings, eaves = sheet.spec.roof, sheet.wings, wing_eaves(sheet)
    main = main_wing(wings)
    own = []
    for i, w in enumerate(wings):
        down = away(wings[main], w)
        pitch = rng.choice(rules.part_pitch_deg)  # жребий — на каждое крыло, как бы ни вышло
        lower = eaves[i] < eaves[main] - EPS
        own.append(house.model_copy(update={
            "kind": RoofKind.SHED, "pitch_deg": pitch, "down_to": down})
            if down is not None and lower else house)
    return own


def _with_gable(rng: random.Random, sheet: FacadeSheet, rules: Composite) -> FacadeSheet:
    """Лист со щипцом над входом, если он встал: крыша строится на одну часть больше."""
    share, pitch = rng.uniform(*rules.wall_gable_share), rng.choice(rules.wall_gable_pitch_deg)
    return entrance_gable.placed(sheet, share, pitch, rules.wall_gable_min_m)
