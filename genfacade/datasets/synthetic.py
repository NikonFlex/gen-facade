"""Синтетические дома, ступень 1: прямоугольный дом (specs/data.md, правила 1 и 9).

Один seed — один дом. Сначала решения (`draft`): размеры, перегородки, вход, окна по участкам
стен между перегородками, намеренно глухие стены. Потом план рисуется в формате GenPlan
и идёт через настоящий препроцессор — как запрос к модулю. Числа — config/synthetic.toml.
"""

import random
from dataclasses import dataclass, replace

from genfacade import pipeline
from genfacade.config import Config, OpeningRules, Synthetic
from genfacade.datasets import genplan_writer
from genfacade.datasets.genplan_writer import Hole, Opening, PlanDraft, Run
from genfacade.models import stub
from genfacade.plan.gaps import Axis
from genfacade.plan.preprocess import ENTRANCE_WIDTH_M, preprocess
from genfacade.schema import Mode, Sample, Source, Split

Span = tuple[float, float]


@dataclass(frozen=True)
class _Wall:
    """Наружная стена до расстановки проёмов: полоса и свободные участки между комнатами."""

    run: Run
    bays: tuple[Span, ...]
    long: bool


def sample(seed: int, cfg: Config) -> Sample:
    """Дом по seed: план через препроцессор и стены без раскладки (раскладка — шаг 4 задачи)."""
    svg = genplan_writer.svg(draft(seed, cfg.synthetic), cfg.synthetic.canvas)
    plan = preprocess(svg, Mode.WITH_OPENINGS, cfg.plan).model_copy(
        update={"source": Source.SYNTHETIC})
    return Sample(id=f"rect-{seed:06d}", source=Source.SYNTHETIC, split=Split.TRAIN, plan=plan,
                  sheet=pipeline.walls(stub.spec_model(""), plan))


def draft(seed: int, cfg: Synthetic) -> PlanDraft:
    rng = random.Random(seed)  # noqa: S311 — воспроизводимость по seed, не криптография
    width = _on_grid(rng, cfg.house.width_m, cfg.house.grid_m)
    depth = min(width, _on_grid(rng, cfg.house.depth_m, cfg.house.grid_m))
    cuts = _cuts(rng, width, cfg)
    walls = _walls(width, depth, cuts, cfg)
    while True:  # дом совсем без окон не нужен — тянем раскладку ещё раз тем же генератором
        runs = _with_openings(rng, walls, cfg.openings)
        if any(o.hole is Hole.WINDOW for r in runs for o in r.openings):
            break
    inner = [_partition(rng, x, depth, cfg) for x in cuts]
    return PlanDraft(width, depth, cfg.house.wall_m, (*runs, *inner))


def _on_grid(rng: random.Random, span: Span, step: float) -> float:
    return round(rng.randint(round(span[0] / step), round(span[1] / step)) * step, 3)


def _cuts(rng: random.Random, width: float, cfg: Synthetic) -> list[float]:
    """Где стоят поперечные перегородки: комнаты не уже min_room_m."""
    room, step = cfg.partitions.min_room_m, cfg.house.grid_m
    cuts: list[float] = []
    for _ in range(rng.randint(0, cfg.partitions.max_count)):
        edges = [0.0, *sorted(cuts), width]
        free = [(a + room, b - room) for a, b in zip(edges, edges[1:], strict=False)
                if b - a >= 2 * room]
        if free:
            cuts.append(_on_grid(rng, rng.choice(free), step))
    return sorted(cuts)


def _walls(width: float, depth: float, cuts: list[float], cfg: Synthetic) -> list[_Wall]:
    """Четыре наружные стены; у длинных участки разделены перегородками, у торцов — один."""
    t, clear = cfg.house.wall_m, cfg.openings.corner_clear_m
    stops = [(0.0, t), *((x, x + t) for x in cuts), (width - t, width)]
    long_bays = tuple((a[1] + clear, b[0] - clear) for a, b in zip(stops, stops[1:], strict=False))
    short_bays = ((t + clear, depth - t - clear),)
    return [
        _Wall(Run(Axis.X, 0.0, 0.0, width), long_bays, True),
        _Wall(Run(Axis.X, depth - t, 0.0, width), long_bays, True),
        _Wall(Run(Axis.Y, 0.0, 0.0, depth), short_bays, False),
        _Wall(Run(Axis.Y, width - t, 0.0, depth), short_bays, False),
    ]


def _with_openings(rng: random.Random, walls: list[_Wall], cfg: OpeningRules) -> list[Run]:
    """Вход на одной стене, окна — на свободных участках стен, не выбранных глухими."""
    widths = rng.sample(cfg.window_widths_m, rng.randint(1, cfg.widths_per_house))
    on_long = rng.random() < cfg.entrance_long_p
    entry = rng.choice([w for w in walls if w.long is on_long])
    runs = []
    for wall in walls:
        bays, found = list(wall.bays), []
        if wall is entry:
            door, bays = _entrance(rng, bays, cfg)
            found.append(door)
        if rng.random() >= (cfg.blind_long_p if wall.long else cfg.blind_short_p):
            found += [o for bay in bays for o in _windows(rng, bay, rng.choice(widths), cfg)]
        runs.append(replace(wall.run, openings=tuple(found)))
    return runs


def _entrance(rng: random.Random, bays: list[Span], cfg: OpeningRules):
    """Вход в случайном участке → (вход, участки): участок входа делится на два по бокам."""
    fits = [b for b in bays if b[1] - b[0] >= ENTRANCE_WIDTH_M]
    lo, hi = rng.choice(fits)
    at = _on_grid(rng, (lo, hi - ENTRANCE_WIDTH_M), cfg.grid_m)
    rest = [(lo, at - cfg.between_m), (at + ENTRANCE_WIDTH_M + cfg.between_m, hi)]
    others = [b for b in bays if b != (lo, hi)]
    return Opening(at, ENTRANCE_WIDTH_M, Hole.ENTRANCE), others + rest


def _windows(rng: random.Random, bay: Span, width: float, cfg: OpeningRules) -> list[Opening]:
    """Ноль, одно или два окна на участке — с равными простенками, как ставят в комнате.

    Считаем в шагах сетки, целыми: иначе округление съедает простенок или отступ от угла.
    """
    g = cfg.grid_m
    room, w, between = (int(round(v / g, 6)) for v in (bay[1] - bay[0], width, cfg.between_m))
    fit = max(0, (room + between) // (w + between))
    weights = cfg.per_bay_weights[:fit + 1]
    n = rng.choices(range(len(weights)), weights)[0]
    pier = max(between, (room - n * w) // (n + 1))  # простенок между окнами — не уже between
    edge = (room - n * w - (n - 1) * pier) // 2
    return [Opening(round(bay[0] + (edge + i * (w + pier)) * g, 3), width, Hole.WINDOW)
            for i in range(n)]


def _partition(rng: random.Random, x: float, depth: float, cfg: Synthetic) -> Run:
    """Перегородка от стены до стены с проходом; к наружным стенам примыкает торцами."""
    t, clear, passage = cfg.house.wall_m, cfg.openings.corner_clear_m, cfg.partitions.passage_m
    at = _on_grid(rng, (t + clear, depth - t - clear - passage), cfg.openings.grid_m)
    return Run(Axis.Y, x, t, depth - t, (Opening(at, passage, Hole.PASSAGE),))
