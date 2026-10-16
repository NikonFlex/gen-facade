"""FID и KID по растрам стен (gf#143, `evaluation: Пять групп метрик`).

Прибор проверяется с двух концов, как остальные метрики (gf#16): эталон против самого себя —
FID ноль, подмена `random` из калибровки (те же окна, расставленные по стене случайно) — дальше
от эталона, чем ответ генератора на других домах.

Стен — по WALLS в выборке: на 64 и меньше оценки FID и KID путают генератор и `random`, со 128
разделение устойчивое (датчик 16.10, docs/tasks/gf-0143.md). Inception на CPU — секунды на
растр, поэтому признаки считаются один раз на модуль.
"""

import numpy
import pytest

from genfacade.metrics import calibrate, visual
from genfacade.schema import Source, Split

HOUSES = 80  # половина в val; у дома четыре стены и больше — WALLS набирается в обеих частях
WALLS = 128


@pytest.fixture(scope="module")
def inception(half_val):
    """Признаки Inception: эталон — стены домов train, генератор и его подмена — домов val."""
    cfg = half_val(HOUSES)
    train, val = (list(calibrate.houses(Source.SYNTHETIC, split, 0, cfg).values())
                  for split in (Split.TRAIN, Split.VAL))
    rng = numpy.random.default_rng(cfg.metrics.seed)
    rows = {"reference": train, "generator": val, "random": calibrate.random(val, rng)}
    v = cfg.metrics.visual
    out = {}
    for name, sheets in rows.items():
        walls = visual.masks(sheets, v)
        assert len(walls) >= WALLS, name
        out[name] = visual.features(walls[:WALLS], v)
    return v, out


def test_reference_against_itself_is_zero(inception):
    v, f = inception
    assert visual.scores(f["reference"], f["reference"], v)["fid"] == pytest.approx(0, abs=1e-2)


@pytest.mark.parametrize("column", ["fid", "kid"])
def test_random_windows_are_farther_than_generator(inception, column):
    v, f = inception
    generator = visual.scores(f["generator"], f["reference"], v)[column]
    assert visual.scores(f["random"], f["reference"], v)[column] > generator
