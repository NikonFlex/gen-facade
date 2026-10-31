"""Слой «отличим ли от настоящего» метрики правдоподобия (gf#210): стены метода против стен
эталона в пространстве признаков `wall_features` (`[realism] features`), признаки — в долях
разброса обеих выборок вместе.

- c2st     — тест двух выборок классификатором (Lopez-Paz, Oquab 2017) в простейшем виде: доля
             стен, которые ближайший сосед относит к своей выборке (точность 1-NN с исключением
             самой точки). 0,5 — выборки не отличить, 1,0 — разделимы целиком. Выборки
             уравниваются случайной подвыборкой: иначе большая выборка выигрывает по счёту.
             Одна подвыборка шумит (±0,024 на 110 реальных стенах, gf#211), поэтому в таблицу
             идёт среднее по нескольким и их разброс — `c2st_subsets` (gf#235).
- density, coverage — Naeem и др. 2020: шар радиусом до k-го соседа вокруг каждой эталонной
             стены; density — сколько шаров в среднем накрывает стену метода (≈ 1 — как эталон),
             coverage — доля эталонных стен, в шаре которых есть стена метода. coverage растёт
             с числом стен метода, поэтому метод больше эталона уравнивается подвыборками, как
             в c2st (`density_coverage_subsets`).
"""

import numpy

from genfacade.config import Realism
from genfacade.metrics import wall_features
from genfacade.schema import FacadeSheet

BLOCK = 256  # строк за проход в _distances: память, не результат


def walls(sheets: list[FacadeSheet], cfg: Realism) -> numpy.ndarray:
    """Признаки стен домов (`wall_features`, `[realism] features`): строка — стена."""
    rows = [row for s in sheets for row in wall_features.of_house(s, cfg)]
    return numpy.array(rows).reshape(len(rows), len(cfg.features))


def standardized(ours: numpy.ndarray, ref: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray]:
    both = numpy.vstack([ours, ref])
    scale = both.std(axis=0)
    scale[scale == 0] = 1.0
    return ours / scale, ref / scale


def c2st(ours: numpy.ndarray, ref: numpy.ndarray, rng: numpy.random.Generator) -> float | None:
    found = c2st_subsets(ours, ref, rng, 1)
    return None if found is None else found[0]


def c2st_subsets(ours: numpy.ndarray, ref: numpy.ndarray, rng: numpy.random.Generator,
                 subsets: int) -> tuple[float, float] | None:
    """c2st по subsets подвыборкам одним генератором: среднее и стандартное отклонение
    одиночных. Расстояния считаются один раз на обе выборки целиком, подвыборка берёт из них
    свои строки: на эталоне в 1000 домов (≈ 4000 стен) пересчёт на каждую — минуты."""
    n = min(len(ours), len(ref))
    if n < 2:
        return None
    both = numpy.vstack([ours, ref])
    d = _distances(both, both)
    label = numpy.repeat([0, 1], n)
    found = []
    for _ in range(subsets):
        pick = numpy.concatenate([rng.choice(len(ours), n, replace=False),
                                  len(ours) + rng.choice(len(ref), n, replace=False)])
        sub = d[numpy.ix_(pick, pick)]
        numpy.fill_diagonal(sub, numpy.inf)
        found.append(numpy.mean(label[sub.argmin(axis=1)] == label))
    return float(numpy.mean(found)), float(numpy.std(found))


def density_coverage(ours: numpy.ndarray, ref: numpy.ndarray, k: int) -> tuple[float, float] | None:
    if len(ref) <= k or not len(ours):
        return None
    return _density_coverage(_inside(ours, ref, k), k)


def density_coverage_subsets(ours: numpy.ndarray, ref: numpy.ndarray, cfg: Realism,
                             rng: numpy.random.Generator) -> tuple[float, float] | None:
    """density и coverage, средние по subsets подвыборкам стен метода размером с эталон; метод
    не больше эталона — по всем его стенам. coverage растёт с числом стен метода: синтетика
    800 стен против 110 реальных — 0,92, по 110 — 0,66 (gf#235), и строка на 505 домах иначе
    несравнима со строками на 27."""
    if len(ref) <= cfg.k or not len(ours):
        return None
    inside = _inside(ours, ref, cfg.k)
    if len(ours) <= len(ref):
        return _density_coverage(inside, cfg.k)
    found = [_density_coverage(inside[rng.choice(len(ours), len(ref), replace=False)], cfg.k)
             for _ in range(cfg.subsets)]
    density, coverage = numpy.mean(found, axis=0)
    return float(density), float(coverage)


def _inside(ours: numpy.ndarray, ref: numpy.ndarray, k: int) -> numpy.ndarray:
    """Стена метода × эталонная стена: стена метода в шаре эталонной."""
    ref_radius = numpy.sort(_distances(ref, ref), axis=1)[:, k]  # 0-й сосед — сама точка
    return _distances(ours, ref) <= ref_radius[None, :]


def _density_coverage(inside: numpy.ndarray, k: int) -> tuple[float, float]:
    return float(inside.sum() / (k * len(inside))), float(inside.any(axis=0).mean())


def _distances(a: numpy.ndarray, b: numpy.ndarray) -> numpy.ndarray:
    """По BLOCK строк a: разность всех пар сразу на 4000 стенах — 1,4 ГБ памяти."""
    return numpy.vstack([numpy.linalg.norm(a[i:i + BLOCK, None, :] - b[None, :, :], axis=2)
                         for i in range(0, len(a), BLOCK)])


def house_density(house: numpy.ndarray, ref: numpy.ndarray, k: int) -> float | None:
    """Оценка правдоподобия одного дома (gf#210, для «лучшего из N» gf#213): density его стен
    против эталона, признаки — в долях разброса дома и эталона вместе. С оценкой хозяина согласна
    в 23 из 24 пар gf#210 и в 23 из 24 пар gf#212 (docs/metrics-results.md, 31.10, gf#243). Дом
    из эталона из ref убирает вызывающий: иначе стена находит в эталоне саму себя."""
    if not len(house):
        return None
    a, b = standardized(house, ref)
    found = density_coverage(a, b, k)
    return None if found is None else found[0]
