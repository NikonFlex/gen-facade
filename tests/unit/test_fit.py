"""Обучение модели шага 4 одной командой (gf#106): крошечная модель на процессоре.
"""

import json

import pytest
import torch

from genfacade.datasets.synthetic import batch
from genfacade.schema import Mode, Source, Split
from genfacade.train import corpus, fit
from genfacade.train.gpt import IGNORE
from genfacade.train.tokens import Mark

# долгий: torch — вне быстрой проверки перед коммитом (gf#165)
pytestmark = pytest.mark.slow

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


def test_model_saved_every_n_epochs(tiny, tmp_path):
    """`fit.save_every`: модель после эпохи N — рядом с итоговой, того же вида; перенос на план
    GenPlan и BuildingNet меряется по ним вне GPU-машины (gf#186)."""
    fit_cfg = tiny.train.fit.model_copy(update={"save_every": 1})
    cfg = tiny.model_copy(update={"train": tiny.train.model_copy(update={"fit": fit_cfg})})
    out = tmp_path / "run"
    fit.run(Source.SYNTHETIC, cfg, out)
    assert sorted(p.name for p in out.glob("model*.pt")) == ["model-e1.pt", fit.MODEL]
    first, last = (torch.load(out / n, weights_only=False) for n in ("model-e1.pt", fit.MODEL))
    assert first.keys() == last.keys() and first["vocabulary"] == last["vocabulary"]


def test_window_shorter_than_corpus_is_refused(at, houses, tmp_path):
    cfg = at("data", VAL_HALF, TINY.replace("[model]", "[model]\nblock = 8"))
    with pytest.raises(corpus.CorpusError, match="окно 8 короче"):
        fit.run(Source.SYNTHETIC, cfg, tmp_path / "run")


PROBE = "\n[probe]\nevery = 1\ncount = 2\n"


def _history(at, extra: str, tmp_path, name: str) -> list[dict]:
    cfg = at("data", VAL_HALF, TINY.replace("dropout = 0.0", "dropout = 0.1") + extra)
    return json.loads(fit.run(Source.SYNTHETIC, cfg, tmp_path / name).read_text())["history"]


def test_probe_measures_blind_mode_every_epoch(at, houses, tmp_path):
    """Датчик gf#148: ответы на условия глухого режима val после каждой эпохи."""
    history = _history(at, PROBE, tmp_path, "probe")
    for h in history:
        assert h["probe"]["count"] == 2
        assert set(h["probe"]) >= {"parsed", "valid_raw", "raw_errors"}


def test_probe_does_not_change_training(at, houses, tmp_path):
    """Датчик сэмплирует своим генератором: потери те же, что без него (dropout включён)."""
    on = _history(at, PROBE, tmp_path, "on")
    off = _history(at, PROBE.replace("every = 1", "every = 0"), tmp_path, "off")
    assert [(h["train"], h["val"]) for h in on] == [(h["train"], h["val"]) for h in off]
    assert all("probe" not in h for h in off)
