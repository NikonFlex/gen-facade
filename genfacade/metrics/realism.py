"""Слой «отличим ли от настоящего» метрики правдоподобия (gf#210): стены метода против стен
эталона в пространстве признаков `measures.realism_features`, признаки — в долях разброса обеих
выборок вместе.

- c2st     — тест двух выборок классификатором (Lopez-Paz, Oquab 2017) в простейшем виде: доля
             стен, которые ближайший сосед относит к своей выборке (точность 1-NN с исключением
             самой точки). 0,5 — выборки не отличить, 1,0 — разделимы целиком. Выборки
             уравниваются случайной подвыборкой: иначе большая выборка выигрывает по счёту.
- density, coverage — Naeem и др. 2020: шар радиусом до k-го соседа вокруг каждой эталонной
             стены; density — сколько шаров в среднем накрывает стену метода (≈ 1 — как эталон),
             coverage — доля эталонных стен, в шаре которых есть стена метода.
"""

import numpy


def standardized(ours: numpy.ndarray, ref: numpy.ndarray) -> tuple[numpy.ndarray, numpy.ndarray]:
    both = numpy.vstack([ours, ref])
    scale = both.std(axis=0)
    scale[scale == 0] = 1.0
    return ours / scale, ref / scale


def c2st(ours: numpy.ndarray, ref: numpy.ndarray, rng: numpy.random.Generator) -> float | None:
    n = min(len(ours), len(ref))
    if n < 2:
        return None
    a = ours[rng.choice(len(ours), n, replace=False)]
    b = ref[rng.choice(len(ref), n, replace=False)]
    x, label = numpy.vstack([a, b]), numpy.repeat([0, 1], n)
    d = _distances(x, x)
    numpy.fill_diagonal(d, numpy.inf)
    return float(numpy.mean(label[d.argmin(axis=1)] == label))


def density_coverage(ours: numpy.ndarray, ref: numpy.ndarray, k: int) -> tuple[float, float] | None:
    if len(ref) <= k or not len(ours):
        return None
    ref_radius = numpy.sort(_distances(ref, ref), axis=1)[:, k]  # 0-й сосед — сама точка
    inside = _distances(ours, ref) <= ref_radius[None, :]
    return float(inside.sum() / (k * len(ours))), float(inside.any(axis=0).mean())


def _distances(a: numpy.ndarray, b: numpy.ndarray) -> numpy.ndarray:
    return numpy.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)


def house_density(house: numpy.ndarray, ref: numpy.ndarray, k: int) -> float | None:
    """Оценка правдоподобия одного дома (gf#210, для «лучшего из N» gf#213): density его стен
    против эталона, признаки — в долях разброса дома и эталона вместе. С оценкой хозяина на 24
    парах согласна в 23 (docs/metrics-results.md, 30.10). Дом из эталона из ref убирает
    вызывающий: иначе стена находит в эталоне саму себя."""
    if not len(house):
        return None
    a, b = standardized(house, ref)
    found = density_coverage(a, b, k)
    return None if found is None else found[0]
