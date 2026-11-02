"""Случайное место окон на стене (`placement = "random"`, gf#217): синтетика «язык».

Формат ответа модель учит на синтетике, а расстановку — на реальных домах, поэтому окна стоят не
по правилам генератора, а случайно в тех же пределах: число окон на стене, x по стене, ширина.
Пределы — участки стены (отступ от угла и перегородки, запретные зоны: их считает вызывающий) и
простенок между окнами. Высоты окон — `openings.scattered`.
"""

import math
import random

from genfacade.config import OpeningRules
from genfacade.datasets.genplan_writer import Hole, Opening

Span = tuple[float, float]


def _units(metres: float, step: float) -> float:
    return round(metres / step, 6)  # хвост float не сдвигает целое


def windows(rng: random.Random, bays: list[Span], widths: list[float], cfg: OpeningRules,
            least: int = 0) -> list[Opening]:
    """Окна стены: их число — равномерно от least до того, сколько уместится на участках (не
    больше per_bay_weights на участок, как у правил); x — равномерно по свободным местам, ширина —
    из widths; простенок — between_m. Не уместилось — окон меньше."""
    g = cfg.grid_m
    free = [(math.ceil(_units(lo, g)), math.floor(_units(hi, g))) for lo, hi in bays]
    sizes = [round(_units(w, g)) for w in widths]
    between = math.ceil(_units(cfg.between_m, g))
    most = len(cfg.per_bay_weights) - 1
    cap = sum(min(most, (hi - lo + between) // (min(sizes) + between)) for lo, hi in free)
    placed: list[Span] = []
    for _ in range(rng.randint(min(least, cap), cap)):
        spot = _spot(rng, free, placed, (sizes, between))
        if spot is None:
            break
        placed.append(spot)
    return [Opening(round(a * g, 3), round((b - a) * g, 3), Hole.WINDOW) for a, b in sorted(placed)]


def _spot(rng: random.Random, free: list[tuple[int, int]], placed: list[tuple[int, int]],
          size: tuple[list[int], int]) -> tuple[int, int] | None:
    """Место окна в шагах сетки: ширина — случайная из доступных, начало — равномерно среди
    свободных; None — ни одно окно уже не влезает."""
    sizes, between = size
    for w in rng.sample(sizes, len(sizes)):
        starts = [u for lo, hi in free for u in range(lo, hi - w + 1)
                  if all(u + w + between <= s or u >= e + between for s, e in placed)]
        if starts:
            u = rng.choice(starts)
            return u, u + w
    return None
