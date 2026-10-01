"""План в формате GenPlan из описания стен с проёмами (plan-input.md, правило 1).

Обратное к plan/genplan_svg.py: стена — чёрный `<rect>`, окно — `<rect>` цвета окна в разрыве,
вход — пустой разрыв, створка и дуга из петли; проход в перегородке — пустой разрыв.
Геометрия задаётся в метрах в осях плана (x вправо, y вверх, дом от нуля); в SVG ось y вниз.
"""

from dataclasses import dataclass
from enum import Enum

from genfacade.config import Canvas
from genfacade.plan.gaps import Axis
from genfacade.plan.genplan_svg import LEAF_PX, WALL_FILL, WINDOW_FILL
from genfacade.schema import Point

Box = tuple[float, float, float, float]  # x0, y0, x1, y1, метры плана


class Hole(Enum):
    WINDOW = "window"
    ENTRANCE = "entrance"
    PASSAGE = "passage"


@dataclass(frozen=True)
class Opening:
    at_m: float  # начало вдоль стены
    width_m: float
    hole: Hole


@dataclass(frozen=True)
class Run:
    """Стена или перегородка: полоса вдоль оси с проёмами."""

    axis: Axis
    across_m: float  # ближняя к нулю грань полосы
    start_m: float
    end_m: float
    openings: tuple[Opening, ...] = ()


@dataclass(frozen=True)
class PlanDraft:
    width_m: float
    depth_m: float
    wall_m: float
    runs: tuple[Run, ...]


def svg(draft: PlanDraft, canvas: Canvas) -> str:
    """Черновик плана → текст SVG, как его написал бы GenPlan."""
    to_px = _Pixels(draft, canvas)
    walls, windows, doors = [], [], []
    for run in draft.runs:
        edges = [run.start_m]
        for o in sorted(run.openings, key=lambda o: o.at_m):
            edges += [o.at_m, o.at_m + o.width_m]
            if o.hole is Hole.WINDOW:
                windows.append(to_px.rect(_band(draft, run, o.at_m, o.at_m + o.width_m)))
            elif o.hole is Hole.ENTRANCE:
                doors += _door(draft, run, o, to_px)
        edges.append(run.end_m)
        walls += [to_px.rect(_band(draft, run, a, b), WALL_FILL)
                  for a, b in zip(edges[::2], edges[1::2], strict=True) if b > a]
    w, h = to_px.size
    head = ('<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">')
    return "\n".join([head, *walls, *doors, *windows, "</svg>"])


class _Pixels:
    """Метры плана → пиксели SVG: поле холста, масштаб, переворот оси y."""

    def __init__(self, draft: PlanDraft, canvas: Canvas):
        self.k, self.pad = canvas.px_per_m, canvas.margin_m * canvas.px_per_m
        self.top = draft.depth_m
        self.size = (round(draft.width_m * self.k + 2 * self.pad),
                     round(draft.depth_m * self.k + 2 * self.pad))

    def point(self, p: Point) -> tuple[int, int]:
        return round(self.pad + p[0] * self.k), round(self.pad + (self.top - p[1]) * self.k)

    def rect(self, box: Box, fill: str = WINDOW_FILL) -> str:
        (x0, y1), (x1, y0) = self.point(box[:2]), self.point(box[2:])
        return f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="{fill}" />'


def _band(draft: PlanDraft, run: Run, a: float, b: float) -> Box:
    """Кусок полосы стены от a до b вдоль её оси."""
    lo, hi = run.across_m, run.across_m + draft.wall_m
    return (a, lo, b, hi) if run.axis is Axis.X else (lo, a, hi, b)


def _door(draft: PlanDraft, run: Run, o: Opening, to_px: _Pixels) -> list[str]:
    """Открытая створка и дуга входа: петля — на внутренней грани у начала разрыва."""
    middle = (draft.depth_m if run.axis is Axis.X else draft.width_m) / 2
    inward = 1 if run.across_m < middle else -1
    face = run.across_m + (draft.wall_m if inward > 0 else 0.0)
    leaf = LEAF_PX / to_px.k
    along = (o.at_m, o.at_m + leaf, o.at_m + o.width_m)  # петля, толщина створки, край разрыва
    across = sorted((face, face + inward * o.width_m))
    if run.axis is Axis.X:
        hinge, jamb, tip = (along[0], face), (along[2], face), (along[0], face + inward * o.width_m)
        box = (along[0], across[0], along[1], across[1])
    else:
        hinge, jamb, tip = (face, along[0]), (face, along[2]), (face + inward * o.width_m, along[0])
        box = (across[0], along[0], across[1], along[1])
    return [to_px.rect(box, WALL_FILL), _arc(*(to_px.point(p) for p in (hinge, jamb, tip)))]


def _arc(hinge: Point, jamb: Point, tip: Point) -> str:
    """Четверть окружности от края разрыва до конца створки, центр — петля (пиксели SVG)."""
    (ax, ay), (bx, by) = (jamb[0] - hinge[0], jamb[1] - hinge[1]), (tip[0] - hinge[0],
                                                                    tip[1] - hinge[1])
    r = round(abs(ax) + abs(ay))
    sweep = 1 if ax * by - ay * bx > 0 else 0  # по часовой стрелке на экране
    return (f'<path d="M{jamb[0]},{jamb[1]} A{r},{r},0,0,{sweep},{tip[0]},{tip[1]}" '
            f'stroke="{WALL_FILL}" fill="none" stroke-width="{LEAF_PX}" />')
