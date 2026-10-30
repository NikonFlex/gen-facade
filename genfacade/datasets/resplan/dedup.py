"""Почти одинаковые планы ResPlan: листинги публикуются повторно (README ResPlan, «Known
limitations»: 1 170 лишних планов, 6,9 %). Признак тот же, что у авторов: растр разметки, IoU не
ниже порога при любом из восьми поворотов и отражений (croissant.json, dataBiases).
Списка дублей в выпуске нет — split.json содержит только train, val, test и augmented.
"""

import numpy
import shapely

from genfacade.config import ResPlan
from genfacade.datasets.resplan.convert import DOOR, FRONT_DOOR, INNER, WALL, WINDOW

# Порядок закраски: позже — поверх. Метка — номер слоя с единицы, 0 — пусто.
LAYERS = ((INNER,), (WALL,), (WINDOW,), (DOOR, FRONT_DOOR))


def raster(plan: dict, n: int) -> numpy.ndarray:
    """Метки слоёв в квадрате n × n; план вписан по центру с сохранением пропорций."""
    x0, y0, x1, y1 = shapely.union_all([plan[INNER], plan[WALL]]).bounds
    k = n / max(x1 - x0, y1 - y0)
    c = (numpy.arange(n) + 0.5) / k
    gx, gy = numpy.meshgrid(c + (x0 + x1) / 2 - n / 2 / k, c + (y0 + y1) / 2 - n / 2 / k)
    out = numpy.zeros((n, n), numpy.uint8)
    for label, keys in enumerate(LAYERS, start=1):
        geoms = [plan[key] for key in keys if plan.get(key) is not None]
        out[shapely.contains_xy(shapely.union_all(geoms), gx, gy)] = label
    return out


def dihedral(a: numpy.ndarray) -> numpy.ndarray:
    """Восемь поворотов и отражений квадратного растра."""
    turns = [numpy.rot90(a, k) for k in range(4)]
    return numpy.stack(turns + [numpy.fliplr(t) for t in turns])


def best_iou(a: numpy.ndarray, others: numpy.ndarray) -> numpy.ndarray:
    """Лучший по восьми положениям `a` IoU разметки с каждым из others (m × n × n)."""
    views = dihedral(a)[:, None]                      # 8 × 1 × n × n
    same = ((views == others) & (others > 0)).sum(axis=(2, 3))
    union = ((views > 0) | (others > 0)).sum(axis=(2, 3))
    return (same / numpy.maximum(union, 1)).max(axis=0)


def clusters(plans: list[dict], rules: ResPlan) -> list[list[int]]:
    """Группы почти дублей (индексы plans); сравниваются планы с близкой площадью листинга."""
    rasters = numpy.stack([raster(p, rules.dedup_raster_px) for p in plans])
    area = numpy.array([float(p["area"]) for p in plans])
    order = numpy.argsort(area)
    parent = list(range(len(plans)))
    for pos, i in enumerate(order):
        near = order[pos + 1:][area[order[pos + 1:]] <= area[i] * (1 + rules.dedup_area_tol)]
        if near.size:
            for j in near[best_iou(rasters[i], rasters[near]) >= rules.dedup_iou]:
                parent[_root(parent, int(j))] = _root(parent, int(i))
    groups: dict[int, list[int]] = {}
    for i in range(len(plans)):
        groups.setdefault(_root(parent, i), []).append(i)
    return list(groups.values())


def _root(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i
