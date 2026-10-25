"""Дом источника с ортогональным контуром → стороны и план: общее у извлечения BuildingNet и ручной
разметки.

Источник даёт контур в плане — прямоугольник (BuildingNet) или ортогональный многоугольник с
внутренними углами (ручная разметка, gf#199) — и элементы каждой стены в координатах стены
(schema: x вдоль стороны от левого края снаружи, y от земли); здесь из них — стороны с проёмами
первого этажа, план со стенами и проёмами и зона основной отделки.
"""

import numpy

from genfacade import pipeline
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    HouseSpec,
    MaterialZone,
    Opening,
    OpeningKind,
    PaletteRole,
    Plan,
    PlanOpening,
    Rect,
    Side,
    SideFacade,
    Source,
    ZoneRole,
)
from genfacade.validate import OPENINGS

# Нормали сторон по часовой стрелке (y плана — вверх): каждая следующая — предыдущая,
# повёрнутая на −90°, как ждёт развёртка (unfold.plan_corners).
NORMALS = ((0.0, 1.0), (1.0, 0.0), (0.0, -1.0), (-1.0, 0.0))


class Wall:
    """Сторона контура в плане — ребро от угла a к углу b по часовой: нормаль, плоскость и отрезок
    вдоль неё."""

    def __init__(self, normal: tuple[float, float], a: numpy.ndarray, b: numpy.ndarray) -> None:
        self.normal, self.a, self.b = numpy.array(normal, dtype=float), a, b
        # Снаружи, лицом к стене, вправо — нормаль, повёрнутая на +90°: x фасада растёт вправо
        # от левого края стороны (schema: координаты на стене).
        self.right = numpy.array((-normal[1], normal[0]), dtype=float)
        self.plane = float(a @ self.normal) + 0.0  # + 0.0: −0.0 от нуля на −1 — в 0.0
        self.left = float(min(a @ self.right, b @ self.right)) + 0.0
        self.length = abs(float((b - a) @ self.right))


class Footprint:
    """Контур дома в плане: углы по часовой, толщина стен плана и стены — ребро на сторону."""

    def __init__(self, vertices: list[numpy.ndarray], normals: list[tuple[float, float]],
                 wall_m: float) -> None:
        self.vertices, self.wall_m = vertices, wall_m
        self.walls = [Wall(n, vertices[k], vertices[(k + 1) % len(vertices)])
                      for k, n in enumerate(normals)]


def rectangle(lo: numpy.ndarray, hi: numpy.ndarray, wall_m: float) -> Footprint:
    """Прямоугольник: стены в порядке NORMALS — верхняя, правая, нижняя, левая."""
    (x0, y0), (x1, y1) = lo, hi
    corners = [numpy.array(p, dtype=float) for p in ((x0, y1), (x1, y1), (x1, y0), (x0, y0))]
    return Footprint(corners, list(NORMALS), wall_m)


def assemble(spec: HouseSpec, fp: Footprint, laid: list[tuple[int, list[Element]]],
             source: Source) -> tuple[Plan, FacadeSheet]:
    """План и лист дома; laid[k] — номер стены в NORMALS и элементы стороны k (сторона 0 —
    сторона входа, дальше по часовой стрелке)."""
    sides = [side(k, fp.walls[i], elements, k == 0) for k, (i, elements) in enumerate(laid)]
    house_plan = plan(fp, sides, [i for i, _ in laid], source)
    sheet = pipeline.walls(spec, house_plan)
    facades = [f.model_copy(update={"elements": elements, "zones": zones(f)})
               for f, (_, elements) in zip(sheet.facades, laid, strict=True)]
    return house_plan, sheet.model_copy(update={"facades": facades})


def floor_of(y: float, spec: HouseSpec) -> int:
    """Этаж по высоте середины элемента: ниже цоколя — первый, выше карниза — последний."""
    tops = spec.floor_levels()[1:-1]
    return 1 + sum(y >= t for t in tops)


def side(index: int, w: Wall, elements: list[Element], entrance_side: bool) -> Side:
    """Проёмы первого этажа — проёмы плана; вход — самая широкая дверь стороны входа."""
    ground = _in_plan([e for e in elements if e.cls in OPENINGS and e.floor == 1])
    doors = [e for e in ground if e.cls is not ElementClass.WINDOW]
    entrance = max(doors, key=lambda e: e.w_m) if entrance_side and doors else None
    openings = [Opening(kind=OpeningKind.WINDOW if e.cls is ElementClass.WINDOW
                        else OpeningKind.ENTRANCE if e is entrance else OpeningKind.DOOR,
                        x_m=e.x_m, width_m=e.w_m) for e in ground]
    return Side(index=index, length_m=w.length, orientation=tuple(w.normal), openings=openings,
                has_entrance=entrance is not None)


def _in_plan(ground: list[Element]) -> list[Element]:
    """Проёмы первого этажа, налезающие друг на друга по x (окно над дверью, окно в окне), в плане —
    один разрыв стены: в план идёт самый широкий, при равной ширине — дверь; остальные остаются на
    фасаде элементами, которые ставит модель (gf#186: у BuildingNet половина простенков уже 0,6 м,
    10-й процентиль −1,4 м — в настоящем плане так не бывает)."""
    kept: list[Element] = []
    for e in sorted(ground, key=lambda e: (-e.w_m, e.cls is ElementClass.WINDOW)):
        if not any(min(e.x_m + e.w_m, k.x_m + k.w_m) - max(e.x_m, k.x_m) > EPS for k in kept):
            kept.append(e)
    return sorted(kept, key=lambda e: e.x_m)


def plan(fp: Footprint, sides: list[Side], order: list[int], source: Source) -> Plan:
    """План по сторонам; order[k] — номер стены контура у стороны k."""
    rects = [_wall_rect(w, fp.wall_m) for w in fp.walls]
    openings = [_plan_opening(o, fp.walls[i], rects[i])
                for s, i in zip(sides, order, strict=True) for o in s.openings]
    # Обход по часовой стрелке; метры — сразу, пикселей у источника нет.
    outline = [(float(v[0]) + 0.0, float(v[1]) + 0.0) for v in fp.vertices]
    return Plan(walls=rects, outline=outline, openings=openings, sides=sides, scale_m_per_px=1.0,
                source=source)


def _wall_rect(w: Wall, t: float) -> Rect:
    """Стена плана — полоса толщиной t внутрь от наружной грани, вдоль всего ребра."""
    (ax, ay), (bx, by), inner = (float(v) + 0.0 for v in w.a), (float(v) + 0.0 for v in w.b), \
        w.plane - t
    if w.normal[1]:  # стена вдоль x: наружная грань — y = plane по нормали
        y_out, y_in = w.plane * w.normal[1] + 0.0, inner * w.normal[1] + 0.0
        return Rect(x0_m=min(ax, bx), y0_m=min(y_out, y_in), x1_m=max(ax, bx),
                    y1_m=max(y_out, y_in))
    x_out, x_in = w.plane * w.normal[0] + 0.0, inner * w.normal[0] + 0.0
    return Rect(x0_m=min(x_out, x_in), y0_m=min(ay, by), x1_m=max(x_out, x_in), y1_m=max(ay, by))


def _plan_opening(o: Opening, w: Wall, rect: Rect) -> PlanOpening:
    """Проём в стене плана: от x до x + ширина вдоль стороны, на всю толщину стены."""
    a, b = (w.left + o.x_m) * w.right, (w.left + o.x_m + o.width_m) * w.right
    if w.normal[1]:  # стена вдоль x
        lo_x, hi_x = sorted((a[0], b[0]))
        return PlanOpening(kind=o.kind, rect=Rect(x0_m=lo_x, y0_m=rect.y0_m, x1_m=hi_x,
                                                  y1_m=rect.y1_m))
    lo_y, hi_y = sorted((a[1], b[1]))
    return PlanOpening(kind=o.kind, rect=Rect(x0_m=rect.x0_m, y0_m=lo_y, x1_m=rect.x1_m,
                                              y1_m=hi_y))


def zones(f: SideFacade) -> list[MaterialZone]:
    """Вся стена — основная отделка: материалы источника в палитру пока не идут."""
    return [MaterialZone(shape=f.silhouette or [], material=PaletteRole.MAIN, role=ZoneRole.MAIN)]
