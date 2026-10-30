"""Метрика правдоподобия (gf#210; `evaluation: Пять групп метрик`, `evaluation: Свод правил
фасада`): слой «отличим ли от настоящего» и слой правил свода.

Каждый слой — с двух концов: выборка из того же распределения неотличима, сдвинутая — отличима;
дом с ровными окнами проходит правила метрики лучше дома с разбросанными.
"""

import numpy

from genfacade.metrics import measures, realism, table
from genfacade.schema import ElementClass

RNG = numpy.random.default_rng(0)
SAME = RNG.normal(size=(200, 4)), RNG.normal(size=(200, 4))
FAR = RNG.normal(size=(200, 4)) + 5.0


def test_c2st_cannot_tell_same_distribution():
    assert abs(realism.c2st(*SAME, numpy.random.default_rng(1)) - 0.5) < 0.1


def test_c2st_separates_shifted_distribution():
    assert realism.c2st(FAR, SAME[1], numpy.random.default_rng(1)) > 0.95


def test_c2st_needs_two_points():
    assert realism.c2st(SAME[0][:1], SAME[1], numpy.random.default_rng(1)) is None


def test_density_and_coverage_of_same_distribution_near_one():
    density, coverage = realism.density_coverage(*SAME, k=5)
    assert 0.7 < density < 1.3
    assert coverage > 0.9


def test_density_and_coverage_of_shifted_distribution_zero():
    assert realism.density_coverage(FAR, SAME[1], k=5) == (0.0, 0.0)


def test_standardized_divides_by_pooled_spread():
    a, b = realism.standardized(numpy.array([[0.0, 1.0]]), numpy.array([[2.0, 1.0]]))
    assert a.tolist() == [[0.0, 1.0]] and b.tolist() == [[2.0, 1.0]]


def test_realism_features_of_blind_wall(house):
    f = house.facades[0].model_copy(update={"elements": []})
    assert measures.realism_features(f, house.spec) == [0.0] * 11


def _with_twins(house, lift):
    """Дом, где у каждого окна — сосед справа через метр; соседа подняли на lift."""
    facades = []
    for f in house.facades:
        twins = [w.model_copy(update={"id": w.id + "b", "x_m": w.x_m + w.w_m + 1.0,
                                      "y_m": w.y_m + lift})
                 for w in f.elements if w.cls is ElementClass.WINDOW
                 and w.x_m + 2 * w.w_m + 1.0 <= f.side.length_m]
        facades.append(f.model_copy(update={"elements": [*f.elements, *twins]}))
    return house.model_copy(update={"facades": facades})


def test_rules_layer_prefers_aligned_windows(house, cfg):
    aligned = table._guidelines([_with_twins(house, 0.0)], cfg)
    scattered = table._guidelines([_with_twins(house, 0.3)], cfg)
    assert aligned["window_head_line"] == 1.0
    assert scattered["window_head_line"] < 1.0
