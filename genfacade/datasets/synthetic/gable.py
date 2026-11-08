"""Окна во фронтоне синтетики (gf#321, `data: Синтетика своим генератором`).

У дома с двускатной крышей с долей `[facade.gable] share` на каждой щипцовой стене — от нуля до
трёх окон этажа под скатом: окно — одного из типоразмеров окон этажей дома (у дома их не больше,
чем допускает свод, — запись токенами не меняет размеров), низ — от карниза на `sill_m`, на оси
конька, а два и три — симметрично с простенком `openings.between_m`; рамка — в стене с отступом
`checks.slope_offset_m` от ската, как держат страж и валидатор. Не влезает — окон меньше, ни одно —
стена без окон; глухая стена глухая и во фронтоне; стена с окнами — без карниза (щипцовая).
Свой поток случайных чисел: при доле ноль дома прежние байт в байт.
"""

import random

import shapely

from genfacade import roof
from genfacade.config import Config
from genfacade.datasets.synthetic.plan import on_grid
from genfacade.schema import EPS, Element, ElementClass, FacadeSheet, RoofKind, VariantKind
from genfacade.train import tokens


def windows(rng: random.Random, sheet: FacadeSheet, cfg: Config) -> list[list[Element]]:
    """Окна во фронтоне каждой стены листа (у стены без фронтона — пусто); sheet — стены с
    окнами этажей."""
    rules, spec = cfg.synthetic.facade.gable, sheet.spec
    none: list[list[Element]] = [[] for _ in sheet.facades]
    if rules.share <= 0 or spec.roof.kind is not RoofKind.GABLE or rng.random() >= rules.share:
        return none
    templates = _templates(sheet, cfg)
    out = []
    for k, (f, above) in enumerate(zip(sheet.facades, roof.gables(sheet), strict=True)):
        blind = not any(e.cls is ElementClass.WINDOW for e in f.elements)  # глухая на всех этажах
        if above is None or not templates or blind:
            out.append([])
            continue
        count = rng.choices(range(len(rules.count_weights)), rules.count_weights)[0]
        y = round(spec.eaves_m + on_grid(rng, rules.sill_m, cfg.synthetic.spec.grid_m), 3)
        room = roof.room(f.side.length_m, spec.eaves_m, above, cfg.checks.slope_offset_m)
        apex = max(above, key=lambda p: p[1])[0]
        axes = [w.x_m + w.w_m / 2 for w in f.elements if w.cls is ElementClass.WINDOW]
        out.append(_fit(rng, k, count, (apex, y), templates, (room, axes), spec.floors + 1, cfg))
    return out


def _templates(sheet: FacadeSheet, cfg: Config) -> list[Element]:
    """Окна этажей дома разных размеров, от меньшего: окно во фронтоне — как одно из них (не
    панорамное — у него нет пола). Пока у дома типоразмеров меньше, чем допускает свод, — ещё и
    низкое окно ширины самого узкого (`windows.narrow_heights_m`): окна во фронтоне у настоящих
    домов ниже окон этажа (0,6–1,5 м против 1,3–1,8, docs/tasks/gf-0321.md)."""
    found: dict[tuple[float, float], Element] = {}
    every = {(w.w_m, w.h_m) for f in sheet.facades for w in f.elements
             if w.cls is ElementClass.WINDOW}
    for f in sheet.facades:
        for w in f.elements:
            panoramic = w.variant is not None and w.variant.kind is VariantKind.PANORAMIC
            if w.cls is ElementClass.WINDOW and not panoramic:
                found.setdefault((w.w_m, w.h_m), w)
    if found and len(every) < tokens.window_types(cfg):
        narrow = found[min(found)]
        for h in cfg.synthetic.facade.windows.narrow_heights_m:
            found.setdefault((narrow.w_m, h), narrow.model_copy(update={"h_m": h}))
            break  # одна высота: типоразмер на дом — один лишний
    return [found[s] for s in sorted(found, key=lambda s: (s[0] * s[1], s))]


def _fit(rng: random.Random, k: int, count: int, at: tuple[float, float],
         templates: list[Element], wall: tuple[shapely.Geometry, list[float]], floor: int,
         cfg: Config) -> list[Element]:
    """Больше всего окон, не больше count, случайного из размеров, что влезают во фронтон; at —
    ось конька и низ окна; wall — место во фронтоне и оси окон этажей стены. Края — на сетке
    синтетики, как у всех проёмов; ряд сдвигается на шаг, если ось окна почти (но не точно)
    совпала с осью окна этажа — валидатор предупредил бы (`axis_align`)."""
    (apex, y), (room, axes), gap = at, wall, cfg.synthetic.openings.between_m
    grid = cfg.synthetic.spec.grid_m
    for n in range(count, 0, -1):
        rows = []
        for t in templates:
            base = [round(round(x / grid) * grid, 3) for x in _row(n, apex, t.w_m, gap)]
            for shift in (0, grid, -grid, 2 * grid, -2 * grid):
                xs = [round(x + shift, 3) for x in base]
                if all(room.contains(_box((x, y, t.w_m, t.h_m))) for x in xs) and not any(
                        cfg.checks.eps_m < abs(x + t.w_m / 2 - a) <= cfg.checks.align_m + grid
                        for x in xs for a in axes):  # запас в шаг: окна этажа сетка сдвигает
                    rows.append((t, xs))
                    break
        if rows:
            t, xs = rng.choice(rows)
            return [Element(id=f"g{k}_{i + 1}", cls=ElementClass.WINDOW, x_m=x, y_m=y,
                            w_m=t.w_m, h_m=t.h_m, floor=floor, variant=t.variant)
                    for i, x in enumerate(xs)]
    return []


def _row(n: int, apex: float, w: float, gap: float) -> list[float]:
    """Левые края n окон шириной w, симметрично оси конька, с простенком gap."""
    span = n * w + (n - 1) * gap
    return [apex - span / 2 + i * (w + gap) for i in range(n)]


def _box(b: tuple[float, float, float, float]) -> shapely.Polygon:
    x, y, w, h = b
    return shapely.box(x + EPS, y + EPS, x + w - EPS, y + h - EPS)
