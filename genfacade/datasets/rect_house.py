"""Прямоугольный дом источника → стороны и план: общее у извлечения BuildingNet и ручной разметки.

Источник даёт прямоугольник в плане и элементы каждой стены в координатах стены (schema: x вдоль
стороны от левого края снаружи, y от земли); здесь из них — стороны с проёмами первого этажа,
план со стенами и проёмами и зона основной отделки.
"""

import numpy

from genfacade import pipeline
from genfacade.schema import (
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
    """Сторона прямоугольного контура в плане: нормаль, плоскость и отрезок вдоль неё."""

    def __init__(self, normal: tuple[float, float], lo: numpy.ndarray, hi: numpy.ndarray) -> None:
        corners = numpy.array([(x, y) for x in (lo[0], hi[0]) for y in (lo[1], hi[1])])
        self.normal = numpy.array(normal)
        # Снаружи, лицом к стене, вправо — нормаль, повёрнутая на +90°: x фасада растёт вправо
        # от левого края стороны (schema: координаты на стене).
        self.right = numpy.array((-normal[1], normal[0]))
        self.plane = float((corners @ self.normal).max())
        self.left = float((corners @ self.right).min())
        self.length = float((corners @ self.right).max()) - self.left


class Footprint:
    """Прямоугольник дома в плане: углы, толщина стен плана и стены в порядке NORMALS."""

    def __init__(self, lo: numpy.ndarray, hi: numpy.ndarray, wall_m: float) -> None:
        self.lo, self.hi, self.wall_m = lo, hi, wall_m
        self.walls = [Wall(n, lo, hi) for n in NORMALS]


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
    ground = [e for e in elements if e.cls in OPENINGS and e.floor == 1]
    doors = [e for e in ground if e.cls is not ElementClass.WINDOW]
    entrance = max(doors, key=lambda e: e.w_m) if entrance_side and doors else None
    openings = [Opening(kind=OpeningKind.WINDOW if e.cls is ElementClass.WINDOW
                        else OpeningKind.ENTRANCE if e is entrance else OpeningKind.DOOR,
                        x_m=e.x_m, width_m=e.w_m) for e in ground]
    return Side(index=index, length_m=w.length, orientation=tuple(w.normal), openings=openings,
                has_entrance=entrance is not None)


def plan(fp: Footprint, sides: list[Side], order: list[int], source: Source) -> Plan:
    """План по сторонам; order[k] — номер стены в NORMALS у стороны k."""
    (x0, y0), (x1, y1), t = fp.lo.tolist(), fp.hi.tolist(), fp.wall_m
    # стены в порядке NORMALS: верхняя, правая, нижняя, левая
    rects = [Rect(x0_m=x0, y0_m=y1 - t, x1_m=x1, y1_m=y1),
             Rect(x0_m=x1 - t, y0_m=y0, x1_m=x1, y1_m=y1),
             Rect(x0_m=x0, y0_m=y0, x1_m=x1, y1_m=y0 + t),
             Rect(x0_m=x0, y0_m=y0, x1_m=x0 + t, y1_m=y1)]
    openings = [_plan_opening(o, fp.walls[i], rects[i])
                for s, i in zip(sides, order, strict=True) for o in s.openings]
    # Обход по часовой стрелке от левого верхнего угла; метры — сразу, пикселей у источника нет.
    return Plan(walls=rects, outline=[(x0, y1), (x1, y1), (x1, y0), (x0, y0)], openings=openings,
                sides=sides, scale_m_per_px=1.0, source=source)


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
