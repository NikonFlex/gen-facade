"""Чтение отрисовки векторизатора (gf#17): что на картинке, а не что внутри SVG.

Путь SVG — не элемент: `ConcatPath` EvoVec склеивает несоприкасающиеся куски одного цвета в один
путь, а путь бывает закрыт сверху другим (порядок слоёв). Поэтому элементы стены берутся с
отрисовки: каждый пиксель → класс ближайшего цвета палитры `[vectorizer.colors]` (сглаживание края
уходит в ближайший класс), связные области (4 соседа) каждого класса, кроме стены, → рамки.
scipy и skimage в проекте нет — области собираются объединением пробегов по строкам.
"""

from typing import NamedTuple

import numpy

from genfacade.config import Config
from genfacade.metrics import visual
from genfacade.schema import ElementClass

Box = tuple[int, int, int, int]  # x0, y0, x1, y1 в пикселях, y вниз, x1 и y1 не входят


class Region(NamedTuple):
    cls: ElementClass
    box: Box
    area: int  # пикселей в области


class Run(NamedTuple):
    x0: int
    x1: int
    cls: int
    node: int


def palette(cfg: Config) -> list[ElementClass]:
    """Классы в порядке, в котором их индексы стоят на `classes()`."""
    return list(cfg.baselines.vectorizer.colors)


def classes(image: numpy.ndarray, cfg: Config) -> numpy.ndarray:
    """H×W индексов `palette()`: класс ближайшего по цвету."""
    colors = numpy.array([visual.rgb(c) for c in cfg.baselines.vectorizer.colors.values()])
    distance = ((image[:, :, None, :].astype(numpy.int32) - colors) ** 2).sum(axis=3)
    return distance.argmin(axis=2)


def visible_share(index: numpy.ndarray, box: Box, cls: int) -> float:
    """Доля рамки, закрашенная классом `cls` на отрисовке; пустая рамка — один пиксель."""
    x0, y0, x1, y1 = box
    patch = index[y0:max(y1, y0 + 1), x0:max(x1, x0 + 1)]
    return float((patch == cls).mean()) if patch.size else 0.0


class Forest:
    """Объединение пробегов: у корня — общая рамка и площадь области."""

    def __init__(self) -> None:
        self.parent: list[int] = []
        self.box: list[list[int]] = []
        self.area: list[int] = []
        self.cls: list[int] = []

    def add(self, x0: int, x1: int, y: int, cls: int) -> int:
        self.parent.append(len(self.parent))
        self.cls.append(cls)
        self.box.append([x0, y, x1, y + 1])
        self.area.append(x1 - x0)
        return len(self.parent) - 1

    def find(self, k: int) -> int:
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def union(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        self.parent[b] = a
        low = [min(p, q) for p, q in zip(self.box[a], self.box[b], strict=True)]
        high = [max(p, q) for p, q in zip(self.box[a], self.box[b], strict=True)]
        self.box[a] = [low[0], low[1], high[2], high[3]]
        self.area[a] += self.area[b]


def runs(row: numpy.ndarray, skip: int) -> list[tuple[int, int, int]]:
    """Пробеги одинаковых значений строки (x0, x1, класс), кроме класса `skip`."""
    cuts = [0, *(numpy.flatnonzero(numpy.diff(row)) + 1).tolist(), len(row)]
    return [(a, b, int(row[a])) for a, b in zip(cuts, cuts[1:], strict=False) if row[a] != skip]


def link(forest: Forest, above: list[Run], below: list[Run]) -> None:
    """Пробеги соседних строк одного класса с общим столбцом — одна область."""
    i = j = 0
    while i < len(above) and j < len(below):
        a, b = above[i], below[j]
        if a.cls == b.cls and a.x0 < b.x1 and b.x0 < a.x1:
            forest.union(a.node, b.node)
        if a.x1 <= b.x1:
            i += 1
        else:
            j += 1


def regions(index: numpy.ndarray, cfg: Config) -> list[Region]:
    """Связные области каждого класса палитры, кроме стены."""
    forest, above, order = Forest(), [], palette(cfg)
    wall = order.index(ElementClass.FACADE)
    for y, row in enumerate(index):
        below = [Run(a, b, c, forest.add(a, b, y, c)) for a, b, c in runs(row, wall)]
        link(forest, above, below)
        above = below
    roots = [k for k in range(len(forest.parent)) if forest.find(k) == k]
    return [Region(order[forest.cls[k]], tuple(forest.box[k]), forest.area[k]) for k in roots]
