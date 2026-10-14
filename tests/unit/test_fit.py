"""Обучение модели шага 4 одной командой (gf#106): крошечная модель на процессоре.

torch — в группе [train], CI его не ставит: без него тесты пропускаются.
"""

import json

import pytest

torch = pytest.importorskip("torch")

from genfacade.datasets.synthetic import batch  # noqa: E402 — после проверки torch
from genfacade.schema import Mode, Source, Split  # noqa: E402
from genfacade.train import corpus, fit  # noqa: E402
from genfacade.train.gpt import IGNORE  # noqa: E402
from genfacade.train.tokens import Mark  # noqa: E402

HOUSES = 6
TINY = """
[model]
layers = 1
heads = 2
width = 16
dropout = 0.0

[fit]
epochs = 2
batch = 4
warmup_steps = 1
device = "cpu"

[sample]
count = 4
batch = 2
"""


VAL_HALF = "[build]\nval_share = 0.5\n"


@pytest.fixture
def houses(at):
    """Шесть домов (половина в val) и их корпус."""
    cfg = at("data", VAL_HALF)
    batch.run(range(HOUSES), cfg)
    corpus.build(Source.SYNTHETIC, cfg)
    return cfg


@pytest.fixture
def tiny(at, houses):
    """Те же дома и крошечная модель в настройках обучения."""
    return at("data", VAL_HALF, TINY)


def test_condition_and_padding_do_not_count_in_loss(tiny):
    data = fit.load(Source.SYNTHETIC, tiny)
    part, pad = data.parts[Split.TRAIN], data.words.index(Mark.END)
    rows = [0, 1]
    x, y = fit.batch(part, rows, pad)
    for k, i in enumerate(rows):
        seq, at = part.ids[i].tolist(), part.answer_at[i]
        assert data.words[seq[at]] == Mark.ANSWER
        assert x[k, :len(seq) - 1].tolist() == seq[:-1]
        assert (y[k, :at] == IGNORE).all()                      # условие
        assert y[k, at:len(seq) - 1].tolist() == seq[at + 1:]  # ответ, со сдвигом на один
        assert (y[k, len(seq) - 1:] == IGNORE).all()            # паддинг
        assert (x[k, len(seq) - 1:] == pad).all()


def test_train_writes_model_curve_and_samples(tiny, tmp_path):
    out = tmp_path / "run"
    settings = json.loads(fit.run(Source.SYNTHETIC, tiny, out).read_text())
    assert [h["epoch"] for h in settings["history"]] == [1, 2]
    assert all(h["train"] > 0 and h["val"] > 0 for h in settings["history"])
    assert (out / fit.MODEL).exists() and (out / "loss.png").exists()
    samples = json.loads((out / fit.SAMPLES).read_text())
    assert samples["count"] == len(samples["rows"]) == 4
    assert samples["parsed"] == sum(r["error"] is None for r in samples["rows"])
    assert sum(v["count"] for v in samples["by_mode"].values()) == 4
    for row in samples["rows"]:
        assert row["tokens"][0] == Mark.ANSWER
        assert row["mode"] in set(Mode)
    assert settings["samples"] == {k: v for k, v in samples.items() if k != "rows"}


def test_window_shorter_than_corpus_is_refused(at, houses, tmp_path):
    cfg = at("data", VAL_HALF, TINY.replace("[model]", "[model]\nblock = 8"))
    with pytest.raises(corpus.CorpusError, match="окно 8 короче"):
        fit.run(Source.SYNTHETIC, cfg, tmp_path / "run")
