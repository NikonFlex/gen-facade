"""Профиль размеров дома по seed: «как GenPlan» или «как реальные» (config/synthetic.toml, [sizes]).

Профиль один на дом: из него берут размеры и план (стороны, ширины окон), и параметры дома
(высота этажа, цоколь) — иначе широкие размеры плана сошлись бы с узкими высотами.
"""

import random

from genfacade.config import Range, Sizes, Synthetic


def pick(seed: int, rules: Synthetic) -> Sizes:
    """Свой поток случайных чисел: доля профилей не сдвигает остальные решения по seed."""
    draw = random.Random(f"sizes/{seed}").random()  # noqa: S311 — не криптография
    mix = rules.sizes
    return mix.real if draw < mix.real_share else mix.genplan


def grid(span: Range, step: float) -> list[float]:
    """Значения на сетке шага от и до: 2,5–3,0 через 0,25 → 2,5 / 2,75 / 3,0."""
    low, high = span
    return [round(low + i * step, 3) for i in range(round((high - low) / step) + 1)]


def rules(cfg: Synthetic, size: Sizes) -> Synthetic:
    """Правила генератора с отступом от угла и простенком профиля, если он их задаёт."""
    own = {k: v for k, v in (("corner_clear_m", size.corner_clear_m),
                             ("between_m", size.between_m)) if v is not None}
    if not own:
        return cfg
    return cfg.model_copy(update={"openings": cfg.openings.model_copy(update=own)})
