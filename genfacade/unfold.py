"""Шаг 3: развёртка стен (facade.md, правило 3).

У каждой стороны плана — прямоугольник стены: длина из плана, высота до карниза из HouseSpec.
Крыша пока только плоская, её на фасаде не видно *(хозяин 01.10)*. Контур — только
прямоугольный: непрямоугольные — открыто в plan-input.md. Высоты из одного HouseSpec, поэтому
соседние фасады сходятся на углах по построению (facade.md, правило 2).
"""

import math

from genfacade.schema import EPS, FacadeSheet, Point, Side


def plan_corners(sides: list[Side]) -> list[Point]:
    """Углы контура в плане: сторона i идёт от угла i к углу i+1, обход по часовой."""
    _check_rectangle(sides)
    corners = [(0.0, 0.0)]
    for s in sides[:-1]:
        nx, ny = s.orientation
        # При обходе по часовой снаружи слева: направление = нормаль, повёрнутая на -90°.
        x, y = corners[-1]
        corners.append((x + ny * s.length_m, y - nx * s.length_m))
    return corners


def _check_rectangle(sides: list[Side]) -> None:
    if len(sides) != 4:
        raise ValueError(f"развёртка пока только для прямоугольного контура, сторон: {len(sides)}")
    for a, b in zip(sides, sides[1:] + sides[:1], strict=True):
        # По часовой нормаль следующей стороны — нормаль текущей, повёрнутая на -90°.
        nx, ny = a.orientation
        if math.dist(b.orientation, (ny, -nx)) > EPS:
            raise ValueError(f"стороны {a.index} → {b.index}: не обход по часовой")
    for a, b in ((sides[0], sides[2]), (sides[1], sides[3])):
        if abs(a.length_m - b.length_m) > EPS:
            raise ValueError(f"стороны {a.index} и {b.index}: противоположные, а длины разные")


def unfold(sheet: FacadeSheet) -> FacadeSheet:
    """Шаг 3: прямоугольник стены у каждой стороны, без крыши; остальное не трогает."""
    eaves = sheet.spec.eaves_m
    facades = [
        f.model_copy(update={"silhouette": [
            (0.0, 0.0), (f.side.length_m, 0.0), (f.side.length_m, eaves), (0.0, eaves)]})
        for f in sheet.facades
    ]
    return sheet.model_copy(update={"facades": facades})
