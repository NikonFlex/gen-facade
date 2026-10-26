"""Ортогональный контур дома BuildingNet по внешним профилям стен (gf#198): Г-, Т-, Z-образные дома.

Прямоугольник (`extract._footprint`) берёт у каждой стороны одну наружную линию стен; у Г-дома её
нет — линия стен у стороны ступенчатая. Здесь внешний профиль стен с каждой из четырёх сторон (самая
наружная стена в каждой полосе шириной `profile_step_m`) задаёт область в плане: точка внутри, если
она не дальше профилей со всех четырёх сторон. Выступы и выемки уже `min_jog_m` (крыльцо, эркер,
ниша) сглаживаются — они элементы на плоскости стены, а не стороны (как в ручной разметке, gf#199).
Граница области — ортогональный многоугольник по часовой; дом без стен с какой-то стороны или с
одной стороной короче `min_side_m` — не дом.
"""

import numpy

from genfacade.datasets.rect_house import NORMALS

Profile = tuple[float, numpy.ndarray]  # начало вдоль стороны и глубина в каждой полосе


def steps(depth: numpy.ndarray, step: float, jog: float) -> numpy.ndarray:
    """Профиль ступенями: перепад глубины меньше jog — та же плоскость стены (обшивка, наличник,
    чуть повёрнутая стена), участок короче jog сливается с соседним, ближайшим по глубине. Без
    этого контур — лесенка из клеток растра."""
    runs: list[list] = []  # [начало, конец, уровень]
    for i, d in enumerate(depth):
        same = runs and (numpy.isfinite(d) == numpy.isfinite(runs[-1][2])) and (
            not numpy.isfinite(d) or abs(d - runs[-1][2]) < jog)
        if same:
            runs[-1][1] = i + 1
            if numpy.isfinite(d):
                runs[-1][2] = max(runs[-1][2], d)
        else:
            runs.append([i, i + 1, d])
    runs = _merge_short(runs, max(1, round(jog / step)))
    out = numpy.empty_like(depth)
    for a, b, level in runs:
        out[a:b] = level
    return out


def _merge_short(runs: list[list], cells: int) -> list[list]:
    """Участки короче cells — в соседний, ближайший по глубине, пока такие есть."""
    while len(runs) > 1 and (k := min(range(len(runs)), key=lambda i: runs[i][1] - runs[i][0])
                             ) is not None and runs[k][1] - runs[k][0] < cells:
        near = [j for j in (k - 1, k + 1) if 0 <= j < len(runs)]
        j = min(near, key=lambda j: abs(runs[j][2] - runs[k][2])
                if numpy.isfinite(runs[j][2]) and numpy.isfinite(runs[k][2]) else numpy.inf)
        lo, hi = min(runs[j][0], runs[k][0]), max(runs[j][1], runs[k][1])
        runs[min(j, k)] = [lo, hi, runs[j][2]]
        del runs[max(j, k)]
    return runs


def region(profiles: list[Profile], step: float) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Клетки плана внутри всех четырёх профилей и начало сетки (x, y) — левый нижний угол.

    Порядок профилей — NORMALS: +y (верх по x справа налево), +x (право по y снизу вверх),
    −y (низ по x слева направо), −x (лево по y сверху вниз): так их строит `_profile` — вдоль
    «правой» оси стороны, повёрнутой нормали."""
    top, right, bottom, left = (_along(p, n, step) for p, n in zip(profiles, NORMALS, strict=True))
    xs_all, ys_all = numpy.concatenate([top[1], bottom[1]]), numpy.concatenate([right[1], left[1]])
    x0, x1 = xs_all.min() - step / 2, xs_all.max() + step / 2
    y0, y1 = ys_all.min() - step / 2, ys_all.max() + step / 2
    xs = x0 + (numpy.arange(max(int((x1 - x0) / step), 0)) + 0.5) * step
    ys = y0 + (numpy.arange(max(int((y1 - y0) / step), 0)) + 0.5) * step
    t, b = _at(top, xs), _at(bottom, xs)
    r, lft = _at(right, ys), _at(left, ys)
    inside = (ys[None, :] <= t[:, None]) & (ys[None, :] >= b[:, None]) & \
             (xs[:, None] <= r[None, :]) & (xs[:, None] >= lft[None, :])
    return inside, numpy.array([x0, y0])


def _along(profile: Profile, normal: tuple[float, float], step: float) -> tuple:
    """Профиль стороны в осях плана: координаты середин полос и граница дома в каждой
    (y для верха и низа, x для боков); полоса без стены — граница бесконечно внутри."""
    first, depth = profile
    nx, ny = normal
    pos = first + (numpy.arange(len(depth)) + 0.5) * step  # вдоль «правой» оси (−ny, nx)
    coord = pos * (nx - ny)  # правая ось — (−ny, nx): у ±y она по ∓x, у ±x — по ±y
    edge = numpy.where(numpy.isfinite(depth), depth * (nx + ny), -numpy.inf * (nx + ny))
    return edge, coord


def _at(side: tuple, where: numpy.ndarray) -> numpy.ndarray:
    """Граница стороны в точках where: ближайшая полоса профиля."""
    edge, coord = side
    order = numpy.argsort(coord)
    idx = numpy.clip(numpy.searchsorted(coord[order], where), 0, len(order) - 1)
    return edge[order][idx]


def smoothed(inside: numpy.ndarray, cells: int) -> numpy.ndarray:
    """Открытие и закрытие квадратом cells × cells: выступы и выемки уже него — не стороны."""
    field = numpy.pad(inside, cells)  # поле: область доходит до края растра, закрытие её не режет
    opened = _dilate(_erode(field, cells), cells)
    return _erode(_dilate(opened, cells), cells)[cells:-cells, cells:-cells]


def _dilate(mask: numpy.ndarray, cells: int) -> numpy.ndarray:
    """Расширение квадратом: по каждой оси — сдвиги на ±cells // 2 с полем, без заворота."""
    r = cells // 2
    out = numpy.pad(mask, r)
    for axis in (0, 1):
        grown = out.copy()
        for shift in range(1, r + 1):
            grown |= numpy.roll(out, shift, axis) | numpy.roll(out, -shift, axis)
        out = grown
    return out[r:out.shape[0] - r, r:out.shape[1] - r] if r else out


def _erode(mask: numpy.ndarray, cells: int) -> numpy.ndarray:
    padded = numpy.pad(~mask, cells, constant_values=True)
    return ~_dilate(padded, cells)[cells:-cells, cells:-cells]


def polygon(inside: numpy.ndarray, origin: numpy.ndarray,
            step: float) -> tuple[list[numpy.ndarray], list[tuple[float, float]]]:
    """Граница области — углы по часовой и наружная нормаль каждой стороны. Область — одна,
    без дыр (её задают профили с четырёх сторон)."""
    edges = _boundary(inside)
    start = min(edges)
    corners, directions, at, walked = [], [], start, 0
    while True:
        nxt, direction = edges[at]
        if not directions or direction != directions[-1]:
            corners.append(numpy.array(at, dtype=float) * step + origin)
            directions.append(direction)
        at, walked = nxt, walked + 1
        if at == start:
            break
    if walked != len(edges):
        raise ValueError(f"не один объём: обойдено {walked} рёбер из {len(edges)}")
    return corners, [_normal(d) for d in directions]


def simplified(corners: list[numpy.ndarray], jog: float) -> tuple[list, list]:
    """Углы ближе jog по x (по y) — на одну линию: ступеньки в клетку растра на стыке профилей у
    углов дома — не стороны. Ортогональность сохраняется: концы вертикальной стороны имеют одну
    x, она и сдвигается целиком. Затем — без нулевых и продолжающих друг друга сторон."""
    snap = [_clusters([c[axis] for c in corners], jog) for axis in (0, 1)]
    points = [numpy.array((snap[0][c[0]], snap[1][c[1]])) for c in corners]
    changed = True
    while changed and len(points) > 4:
        changed = False
        for k in range(len(points)):
            a, b, c = points[k - 1], points[k], points[(k + 1) % len(points)]
            (ux, uy), (vx, vy) = b - a, c - b
            if numpy.allclose(a, b) or abs(ux * vy - uy * vx) < 1e-9:  # нулевая или на прямой
                del points[k]
                changed = True
                break
    directions = [_unit(points[(k + 1) % len(points)] - points[k]) for k in range(len(points))]
    return points, [_normal(d) for d in directions]


def _clusters(values: list[float], gap: float) -> dict[float, float]:
    """Значение → середина его группы: группа — подряд идущие значения с шагом меньше gap."""
    order, out, group = sorted(set(values)), {}, []
    for v in order + [numpy.inf]:
        if group and v - group[-1] >= gap:
            mid = float(numpy.median(group))
            out.update(dict.fromkeys(group, mid))
            group = []
        group.append(v)
    return out


def _unit(v: numpy.ndarray) -> tuple[int, int]:
    return (int(numpy.sign(round(v[0], 9))), int(numpy.sign(round(v[1], 9))))


def _boundary(inside: numpy.ndarray) -> dict:
    """Рёбра клеток на границе, по часовой (y вверх): узел → (следующий узел, направление)."""
    pad = numpy.pad(inside, 1)
    out = {}
    for i, j in zip(*numpy.nonzero(inside), strict=True):
        a, b = i + 1, j + 1  # в pad
        if not pad[a, b + 1]:   # сверху пусто — ребро слева направо
            out[(i, j + 1)] = ((i + 1, j + 1), (1, 0))
        if not pad[a + 1, b]:   # справа пусто — сверху вниз
            out[(i + 1, j + 1)] = ((i + 1, j), (0, -1))
        if not pad[a, b - 1]:   # снизу пусто — справа налево
            out[(i + 1, j)] = ((i, j), (-1, 0))
        if not pad[a - 1, b]:   # слева пусто — снизу вверх
            out[(i, j)] = ((i, j + 1), (0, 1))
    return out


def _normal(direction: tuple[int, int]) -> tuple[float, float]:
    """По часовой снаружи слева: нормаль — направление, повёрнутое на +90°."""
    dx, dy = direction
    return (float(-dy) + 0.0, float(dx) + 0.0)
