"""Шаг 3: развёртка стен (`facade: Стена до карниза`).

У каждой стороны плана — прямоугольник стены: длина из плана, высота до карниза из HouseSpec.
Крыша пока только плоская, её на фасаде не видно *(хозяин 01.10)*. Контур — ортогональный
многоугольник: прямоугольник, Г-, Т-образный (`data: Ступени данных`, третья ступень, gf#199);
незамкнутый или с поворотом не на ±90° отрисовка (оси — от углов, plan_corners) отклоняет с
причиной (PlanError) до первого файла шага 3. Высоты из одного HouseSpec, поэтому соседние
фасады сходятся на углах по построению (`facade: Общие параметры дома`).
"""

import math

from genfacade.plan.genplan_svg import PlanError
from genfacade.schema import EPS, FacadeSheet, Point, Side


def plan_corners(sides: list[Side]) -> list[Point]:
    """Углы контура в плане: сторона i идёт от угла i к углу i+1, обход по часовой."""
    _check_contour(sides)
    corners = [(0.0, 0.0)]
    for s in sides[:-1]:
        nx, ny = s.orientation
        # При обходе по часовой снаружи слева: направление = нормаль, повёрнутая на -90°.
        x, y = corners[-1]
        corners.append((x + ny * s.length_m, y - nx * s.length_m))
    return corners


def _check_contour(sides: list[Side]) -> None:
    """Ортогональный контур по часовой: нормаль следующей стороны — нормаль текущей, повёрнутая
    на ±90° (−90° — внешний угол, +90° — внутренний), внешних углов на четыре больше внутренних,
    и обход возвращается в начало."""
    turns = 0
    for a, b in zip(sides, sides[1:] + sides[:1], strict=True):
        nx, ny = a.orientation
        if math.dist(b.orientation, (ny, -nx)) <= EPS:
            turns += 1
        elif math.dist(b.orientation, (-ny, nx)) <= EPS:
            turns -= 1
        else:
            raise PlanError(f"стороны {a.index} → {b.index}: поворот не на ±90°")
    if turns != 4:
        raise PlanError(f"контур не обходится по часовой: внешних углов больше внутренних на "
                        f"{turns}, нужно 4")
    x = y = 0.0
    for s in sides:
        nx, ny = s.orientation
        x, y = x + ny * s.length_m, y - nx * s.length_m
    if math.hypot(x, y) > EPS * len(sides):
        raise PlanError(f"контур не замкнулся: обход кончился в {math.hypot(x, y):.3f} м от начала")


def unfold(sheet: FacadeSheet) -> FacadeSheet:
    """Шаг 3: прямоугольник стены у каждой стороны, без крыши; остальное не трогает."""
    eaves = sheet.spec.eaves_m
    facades = [
        f.model_copy(update={"silhouette": [
            (0.0, 0.0), (f.side.length_m, 0.0), (f.side.length_m, eaves), (0.0, eaves)]})
        for f in sheet.facades
    ]
    return sheet.model_copy(update={"facades": facades})
