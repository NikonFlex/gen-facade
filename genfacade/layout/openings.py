"""Проёмы стены: двери из плана, окна из плана (режим 2) или по ритму осей (режим 1).

Окна стоят столбцами: одно положение по горизонтали — на всех этажах, как на фасадах
малоэтажных домов. Высоты — доли высоты этажа (config/layout.toml, как WindowSizeType GenPlan).
"""

import math
import random
from dataclasses import dataclass

from genfacade.config import Blind, LayoutRule, Windows
from genfacade.schema import EPS, Element, HouseSpec, Mode, OpeningVariant, Side

Span = tuple[float, float]


@dataclass(frozen=True)
class Rhythm:
    """Ширина окна и шаг осей — один выбор на дом, чтобы стороны были в одном ритме."""

    width_m: float
    pitch_m: float

    @classmethod
    def pick(cls, seed: int, blind: Blind) -> "Rhythm":
        rng = random.Random(seed)  # noqa: S311 — разнообразие раскладки, не криптография
        return cls(rng.choice(blind.widths_m), rng.choice(blind.pitches_m))


@dataclass(frozen=True)
class Column:
    """Положение окна по горизонтали; fixed — задано планом (режим 2)."""

    x_m: float
    w_m: float
    fixed: bool = False


def doors(side: Side, spec: HouseSpec, rule: LayoutRule) -> list[Element]:
    """Вход и прочие наружные двери — из плана в обоих режимах, на пол первого этажа."""
    return [
        Element(id=f"d{i + 1}", cls="door", x_m=o.x_m, y_m=spec.plinth_m, w_m=o.width_m,
                h_m=rule.door.height_m, floor=1, fixed=["x_m", "w_m"])
        for i, o in enumerate(o for o in side.openings if o.kind in ("door", "entrance"))
    ]


def columns(side: Side, mode: Mode, rhythm: Rhythm, blind: Blind) -> tuple[list[Column], ...]:
    """Столбцы окон всех этажей и добавочные над дверями — только для верхних этажей."""
    width = rhythm.width_m
    if mode == "with_openings":
        main = [Column(o.x_m, o.width_m, fixed=True) for o in side.openings if o.kind == "window"]
    else:
        main = _rhythm(_free(side, blind, with_doors=True), rhythm, blind)
    over_doors = [
        Column(o.x_m + (o.width_m - width) / 2, width)
        for o in side.openings if o.kind in ("door", "entrance")
    ]
    free_above = _free(side, blind, with_doors=False)
    return main, [c for c in over_doors if _inside(c, free_above)]


def windows(cols: tuple[list[Column], list[Column]], spec: HouseSpec, size: str,
            cfg: Windows) -> list[Element]:
    main, upper_only = cols
    low, high = cfg.size[size]
    bases = spec.floor_levels()[:-1]  # низ каждого этажа; последняя отметка — верх
    out = []
    for floor, (base, fh) in enumerate(zip(bases, spec.floor_heights_m, strict=True), start=1):
        for c in main + (upper_only if floor > 1 else []):
            y = base + low * fh
            h = min(base + high * fh, base + fh - cfg.lintel_m) - y
            fixed = ["x_m", "w_m"] if c.fixed and floor == 1 else []
            out.append(Element(id=f"w{floor}_{len(out) + 1}", cls="window", x_m=c.x_m, y_m=y,
                               w_m=c.w_m, h_m=h, floor=floor, fixed=fixed,
                               variant=_variant(c.w_m, h, size, cfg)))
    return out


def _variant(w: float, h: float, size: str, cfg: Windows) -> OpeningVariant:
    kind = "panoramic" if size == "high" else "regular"
    rows = 2 if h >= cfg.transom_min_h_m else 1
    return OpeningVariant(kind=kind, cols=max(1, math.ceil(w / cfg.sash_max_w_m - EPS)), rows=rows)


def _free(side: Side, blind: Blind, with_doors: bool) -> list[Span]:
    """Где можно ставить окна: от угла до угла минус запретные зоны и двери с зазором."""
    c = blind.clearance_m
    busy = [(z.x0_m - c, z.x1_m + c) for z in side.forbidden]
    if with_doors:
        busy += [(o.x_m - c, o.x_m + o.width_m + c) for o in side.openings
                 if o.kind in ("door", "entrance")]
    spans = [(blind.edge_m, side.length_m - blind.edge_m)]
    for b0, b1 in busy:
        spans = [piece for s in spans for piece in _cut(s, b0, b1)]
    return [s for s in spans if s[1] - s[0] > EPS]


def _cut(span: Span, b0: float, b1: float) -> list[Span]:
    a0, a1 = span
    if b1 <= a0 or b0 >= a1:
        return [span]
    return [p for p in ((a0, b0), (b1, a1)) if p[1] - p[0] > EPS]


def _rhythm(spans: list[Span], rhythm: Rhythm, blind: Blind) -> list[Column]:
    """В каждом свободном отрезке — окна с шагом осей около выбранного, поровну по отрезку."""
    width, pitch = rhythm.width_m, rhythm.pitch_m
    out = []
    for a, b in spans:
        length = b - a
        fits = int((length + blind.min_gap_m) // (width + blind.min_gap_m))
        n = min(fits, max(1, round(length / pitch)))
        gap = (length - n * width) / (n + 1)
        out += [Column(a + gap + i * (width + gap), width) for i in range(n)]
    return out


def _inside(c: Column, spans: list[Span]) -> bool:
    return any(a - EPS <= c.x_m and c.x_m + c.w_m <= b + EPS for a, b in spans)
