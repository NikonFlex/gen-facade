"""Разбор SVG GenPlan в примитивы: стены, окна, двери — в пикселях и осях SVG (y вниз).

Формат (plan-input.md, правило 1) сверен с кодом GenPlan HEAD 2ed651c:
`dto/rect.py`, `dto/opened_door/opened_door.py`, `decorator/decoration.py`.
- стена — `<rect>` `#000000`, окно — `<rect>` `#99ccff` в разрыве стены;
- дверь (и вход, и внутренняя) — пустой разрыв, рядом открытая створка: чёрный
  `<rect>` толщиной 5 px и дуга `<path d="M… A…">` из петли. У створки в положении
  UP GenPlan не пишет `fill` — по правилам SVG это чёрный;
- план до decorator GenPlan — только стены, проёмы тогда ищутся по разрывам.
Что проём, а что нет, решает препроцессор по контуру (правило 5); здесь только чтение.
"""

import math
import pyexpat
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from genfacade.schema import Point, Rect

SVG_NS = "{http://www.w3.org/2000/svg}"
WALL_FILL = "#000000"
WINDOW_FILL = "#99ccff"
SVG_DEFAULT_FILL = "#000000"
LEAF_PX = 5  # толщина створки: DOOR_WIDTH в config.py GenPlan
# GenPlan пишет дугу с хвостами float (249.99999999999997): точки сравниваем с допуском.
TOL_PX = 1.0
_ARC = re.compile(
    r"M\s*([-\d.eE]+)[ ,]+([-\d.eE]+)\s*A\s*([-\d.eE]+)[ ,]+[-\d.eE]+[ ,]+"
    r"[-\d.eE]+[ ,]+[01][ ,]+[01][ ,]+([-\d.eE]+)[ ,]+([-\d.eE]+)\s*$"
)
_IGNORED_TAGS = {"svg", "defs"}  # drawsvg в GenPlan пишет только их, <rect> и <path>
# С expat 2.6.0 стандартный парсер не подвержен billion laughs, quadratic blowup и большим
# токенам; внешние сущности xml.etree не раскрывает (docs.python.org/3.12/library/xml.html).
# Поэтому чужой SVG читаем без defusedxml, но на старом expat отказываемся.
SAFE_EXPAT = (2, 6, 0)


class PlanError(ValueError):
    """План не читается или дефектен; текст — причина отказа (plan-input.md, правило 7)."""


@dataclass(frozen=True)
class Box:
    """Осевой прямоугольник в пикселях SVG."""

    x0: float
    y0: float
    x1: float
    y1: float

    def contains(self, p: Point) -> bool:
        x, y = p
        inside_x = self.x0 - TOL_PX <= x <= self.x1 + TOL_PX
        return inside_x and self.y0 - TOL_PX <= y <= self.y1 + TOL_PX


@dataclass(frozen=True)
class DoorSwing:
    """Дверь как отрезок на грани стены: от петли до другого края разрыва."""

    hinge: Point
    jamb: Point

    @property
    def width_px(self) -> float:
        return math.dist(self.hinge, self.jamb)


@dataclass(frozen=True)
class GenPlanSvg:
    width: float
    height: float
    walls: list[Box]
    windows: list[Box]
    doors: list[DoorSwing]


def parse(svg: Path | str) -> GenPlanSvg:
    """SVG GenPlan (путь или текст) → стены, окна, двери; створки из стен убраны."""
    root = _load(svg)
    width, height = _canvas(root)
    walls, windows, arcs = [], [], []
    for el in root.iter():
        tag = el.tag.removeprefix(SVG_NS)
        if el.get("transform") is not None:
            raise PlanError(f"<{tag}> с transform — в SVG GenPlan их не бывает")
        if tag == "rect":
            fill = (el.get("fill") or SVG_DEFAULT_FILL).lower()
            _rects_by_fill(fill, walls, windows).append(_box(el))
        elif tag == "path":
            arcs.append(_arc(el.get("d") or ""))
        elif tag not in _IGNORED_TAGS:
            raise PlanError(f"неожиданный элемент <{tag}>")
    doors = [_door(arc, walls) for arc in arcs]
    return GenPlanSvg(width, height, walls, windows, doors)


def box_to_rect(box: Box, scale_m_per_px: float, height_px: float) -> Rect:
    """Пиксели SVG (y вниз) → метры плана (y вверх от низа холста)."""
    return Rect(
        x0_m=box.x0 * scale_m_per_px,
        y0_m=(height_px - box.y1) * scale_m_per_px,
        x1_m=box.x1 * scale_m_per_px,
        y1_m=(height_px - box.y0) * scale_m_per_px,
    )


def _load(svg: Path | str) -> ElementTree.Element:
    if pyexpat.version_info < SAFE_EXPAT:
        raise PlanError(f"expat {pyexpat.EXPAT_VERSION} уязвим к XML-бомбам, нужен от 2.6.0")
    try:
        if isinstance(svg, Path):
            return ElementTree.parse(svg).getroot()  # noqa: S314 — см. SAFE_EXPAT
        return ElementTree.fromstring(svg)  # noqa: S314 — см. SAFE_EXPAT
    except ElementTree.ParseError as e:
        raise PlanError(f"SVG не разбирается: {e}") from e


def _canvas(root: ElementTree.Element) -> tuple[float, float]:
    view_box = root.get("viewBox")
    if not view_box:
        raise PlanError("нет viewBox: drawsvg в GenPlan пишет его всегда")
    x, y, w, h = (float(v) for v in view_box.replace(",", " ").split())
    if x or y:
        raise PlanError(f"viewBox не от нуля: {view_box}")
    return w, h


def _rects_by_fill(fill: str, walls: list[Box], windows: list[Box]) -> list[Box]:
    if fill == WALL_FILL:
        return walls
    if fill == WINDOW_FILL:
        return windows
    raise PlanError(f"<rect> неизвестного цвета {fill}: стена {WALL_FILL}, окно {WINDOW_FILL}")


def _box(el: ElementTree.Element) -> Box:
    x, y, w, h = (float(el.get(k, 0)) for k in ("x", "y", "width", "height"))
    if w <= 0 or h <= 0:
        raise PlanError(f"<rect> нулевого размера в ({x}, {y})")
    return Box(x, y, x + w, y + h)


def _arc(d: str) -> tuple[Point, Point, float]:
    """Дуга двери: две конечные точки и радиус."""
    m = _ARC.match(d.strip())
    if not m:
        raise PlanError(f"<path> — не дуга двери GenPlan: {d!r}")
    x0, y0, r, x1, y1 = (float(v) for v in m.groups())
    return (x0, y0), (x1, y1), r


def _door(arc: tuple[Point, Point, float], walls: list[Box]) -> DoorSwing:
    """Найти створку дуги и убрать её из стен.

    Дуга — четверть окружности из петли, концы на осях петли; петля — один из двух углов
    (p.x, q.y) или (q.x, p.y). Створка — прямоугольник радиус × LEAF_PX от петли до одного
    конца дуги, второй конец — край разрыва. Так во всех четырёх положениях створки
    (tests/fixtures/genplan).
    """
    p, q, r = arc
    for hinge in ((p[0], q[1]), (q[0], p[1])):
        for tip, jamb in ((p, q), (q, p)):
            leaves = (w for w in walls if _is_leaf(w, r) and w.contains(hinge) and w.contains(tip))
            leaf = next(leaves, None)
            if leaf is not None:
                walls.remove(leaf)
                return DoorSwing(hinge, jamb)
    raise PlanError(f"дуга двери из {p} в {q} без створки")


def _is_leaf(box: Box, radius: float) -> bool:
    short, long = sorted((box.x1 - box.x0, box.y1 - box.y0))
    return abs(short - LEAF_PX) <= TOL_PX and abs(long - radius) <= TOL_PX
