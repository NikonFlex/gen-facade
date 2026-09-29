"""Шаг 3: силуэт каждой стены и видимая крыша из HouseSpec и сторон (facade.md, правило 3).

Пока только прямоугольный контур: непрямоугольные — открыто в plan-input.md.
Высоты считаются из одного HouseSpec, поэтому соседние фасады сходятся на углах
по построению (facade.md, правило 2).
"""

import math

from genfacade.schema import FacadeSheet, HouseSpec, Point, Polygon, Side

ROOF_THICKNESS_M = 0.2  # видимая толщина ската на торце; только для отрисовки


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
        if math.dist(b.orientation, (ny, -nx)) > 1e-6:
            raise ValueError(f"стороны {a.index} → {b.index}: не обход по часовой")
    for a, b in ((sides[0], sides[2]), (sides[1], sides[3])):
        if abs(a.length_m - b.length_m) > 1e-6:
            raise ValueError(f"стороны {a.index} и {b.index}: противоположные, а длины разные")


def along_ridge(side: Side, ridge_axis: str) -> bool:
    """Сторона параллельна коньку (карнизная), а не торцевая."""
    nx, _ = side.orientation
    # Нормаль вдоль x — стена идёт вдоль y, и наоборот.
    runs_along_x = abs(nx) < 0.5
    return runs_along_x == (ridge_axis == "x")


def ridge_height(spec: HouseSpec, sides: list[Side]) -> float:
    """Отметка конька; у плоской крыши — отметка карниза."""
    roof = spec.roof
    if roof.kind == "flat":
        return spec.eaves_m
    if roof.kind == "shed":
        raise NotImplementedError("односкатная крыша: где высокий край — открыто в facade.md")
    gable_end = next(s for s in sides if not along_ridge(s, roof.ridge_axis))
    return spec.eaves_m + gable_end.length_m / 2 * math.tan(math.radians(roof.pitch_deg))


def wall_silhouette(spec: HouseSpec, side: Side, ridge: float) -> Polygon:
    """Стена от земли до карниза; у торца двускатной крыши — с фронтоном."""
    length, eaves = side.length_m, spec.eaves_m
    wall = [(0.0, 0.0), (length, 0.0), (length, eaves)]
    if spec.roof.kind == "gable" and not along_ridge(side, spec.roof.ridge_axis):
        wall.append((length / 2, ridge))
    wall.append((0.0, eaves))
    return wall


def roof_outline(spec: HouseSpec, side: Side, ridge: float) -> Polygon | None:
    """Видимая со стороны часть крыши; свес опускает край ниже карниза."""
    roof, length, eaves = spec.roof, side.length_m, spec.eaves_m
    if roof.kind == "flat":
        return None
    o = roof.overhang_m
    low = eaves - o * math.tan(math.radians(roof.pitch_deg))
    if along_ridge(side, roof.ridge_axis):
        top = _ridge_span(spec, side, ridge)
        return [(-o, low), (length + o, low), (top[1], ridge), (top[0], ridge)]
    if roof.kind == "gable":
        # Торец: фронтон виден целиком, крыша — полосой по скатам толщиной ROOF_THICKNESS_M.
        d = ROOF_THICKNESS_M / math.cos(math.radians(roof.pitch_deg))
        return [(-o, low), (length / 2, ridge), (length + o, low),
                (length + o, low + d), (length / 2, ridge + d), (-o, low + d)]
    return [(-o, low), (length + o, low), (length / 2, ridge)]


def _ridge_span(spec: HouseSpec, side: Side, ridge: float) -> Point:
    """Концы конька на карнизной стороне: у вальмы конёк короче стены."""
    o = spec.roof.overhang_m
    if spec.roof.kind != "hip":
        return (-o, side.length_m + o)
    half_depth = (ridge - spec.eaves_m) / math.tan(math.radians(spec.roof.pitch_deg))
    x0 = min(half_depth, side.length_m / 2)
    return (x0, side.length_m - x0)


def unfold(sheet: FacadeSheet) -> FacadeSheet:
    """Заполняет силуэт и крышу у каждой стороны; остальное не трогает."""
    sides = [f.side for f in sheet.facades]
    plan_corners(sides)  # проверка контура
    ridge = ridge_height(sheet.spec, sides)
    facades = [
        f.model_copy(update={
            "silhouette": wall_silhouette(sheet.spec, f.side, ridge),
            "roof": roof_outline(sheet.spec, f.side, ridge),
        })
        for f in sheet.facades
    ]
    return sheet.model_copy(update={"facades": facades})
