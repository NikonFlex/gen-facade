"""Метрика правдоподобия (gf#210; `evaluation: Пять групп метрик`, `evaluation: Свод правил
фасада`): слой «отличим ли от настоящего» и слой правил свода.

Каждый слой — с двух концов: выборка из того же распределения неотличима, сдвинутая — отличима;
дом с ровными окнами проходит правила метрики лучше дома с разбросанными.
"""

import numpy

from genfacade import config
from genfacade.metrics import calibrate, realism, table
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


def test_c2st_over_subsets_steadier_than_single(cfg):
    """gf#235: среднее по подвыборкам ближе к 0,5, чем худшая одиночная, и разброс не нулевой.
    Выборки разного размера (как 800 синтетических стен против 110 реальных): одиночные
    подвыборки меньшей выборки шумят. Подвыборок — из настройки, иначе тест не видит её."""
    subsets = cfg.metrics.realism.subsets
    small = SAME[1][:40]
    singles = [realism.c2st(SAME[0], small, numpy.random.default_rng(s)) for s in range(subsets)]
    mean, sd = realism.c2st_subsets(SAME[0], small, numpy.random.default_rng(0), subsets)
    assert abs(mean - 0.5) < max(abs(c - 0.5) for c in singles)
    assert sd > 0
    assert realism.c2st_subsets(SAME[0], small, numpy.random.default_rng(0), 1)[1] == 0


def test_table_takes_subsets_from_config(house, cfg, tmp_path):
    """Строка таблицы: c2st_sd > 0 при подвыборках из настройки и 0 при одной — таблица не
    подменяет настройку своим числом. Эталон — стены дома с шумом, впятеро больше стен метода."""
    walls = realism.walls([house], cfg.metrics.realism)
    noisy = numpy.repeat(walls, 5, axis=0)
    noisy += numpy.random.default_rng(2).normal(size=noisy.shape)
    ref = table.Reference({}, [], None, noisy)
    (tmp_path / "metrics.toml").write_text("[realism]\nsubsets = 1\n")
    many = table._realism([house], ref, cfg)
    one = table._realism([house], ref, config.load(tmp_path))
    assert many["c2st_sd"] > 0 and one["c2st_sd"] == 0


def test_density_and_coverage_of_same_distribution_near_one():
    density, coverage = realism.density_coverage(*SAME, k=5)
    assert 0.7 < density < 1.3
    assert coverage > 0.9


def test_coverage_of_larger_method_taken_at_reference_size(cfg):
    """gf#235: coverage растёт с числом стен метода — метод впятеро больше эталона уравнивается
    подвыборками, и coverage ниже, чем по всем стенам; метод не больше эталона — все стены."""
    small, rng, settings = SAME[1][:40], numpy.random.default_rng(0), cfg.metrics.realism
    full = realism.density_coverage(SAME[0], small, settings.k)
    assert realism.density_coverage_subsets(SAME[0], small, settings, rng)[1] < full[1]
    assert realism.density_coverage_subsets(small, SAME[0], settings, rng) == \
        realism.density_coverage(small, SAME[0], settings.k)


def test_density_and_coverage_of_shifted_distribution_zero():
    assert realism.density_coverage(FAR, SAME[1], k=5) == (0.0, 0.0)


def test_standardized_divides_by_pooled_spread():
    a, b = realism.standardized(numpy.array([[0.0, 1.0]]), numpy.array([[2.0, 1.0]]))
    assert a.tolist() == [[0.0, 1.0]] and b.tolist() == [[2.0, 1.0]]


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


def test_house_density_prefers_house_from_reference_distribution():
    assert realism.house_density(SAME[0][:4], SAME[1], k=5) > 0.5
    assert realism.house_density(FAR[:4], SAME[1], k=5) == 0.0
    assert realism.house_density(SAME[0][:0], SAME[1], k=5) is None


def test_real_house_beats_its_random_substitute_on_rules(house, cfg):
    """Тот же дом с подменой `random` (окна раскиданы по стене) проходит правила метрики хуже."""
    real = _with_twins(house, 0.0)
    fake = calibrate.ROWS["random"]([real], numpy.random.default_rng(0))[0]
    score = {name: numpy.mean(list(table._guidelines([s], cfg).values()))
             for name, s in (("real", real), ("fake", fake))}
    assert score["real"] > score["fake"]
