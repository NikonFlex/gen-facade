"""Модель шага 4 (gf#107): сэмплирование с KV-кэшем даёт тот же ответ, что без кэша;
чекпойнт грузится, условие кончается `<answer>`, чужой словарь — отказ.
"""

import pytest
import tiny_model
import torch

from genfacade.config import GPTSize, Sampling
from genfacade.models import layout
from genfacade.models.stub import ModelError
from genfacade.schema import Device, Mode
from genfacade.train import sampling, tokens
from genfacade.train.tokens import Mark, TokenError

VOCAB, LENGTH = 11, 12
TINY = GPTSize(block=16, layers=2, heads=2, width=8, dropout=0.0)


@pytest.fixture
def model():
    torch.manual_seed(0)
    return sampling.build_model(TINY, VOCAB).eval()


def test_cached_step_gives_the_same_logits_as_full_pass(model):
    idx = torch.randint(0, VOCAB, (3, LENGTH))
    prompt = 4
    with torch.no_grad():
        logits, past = model.step(idx[:, :prompt])
        cached = [logits]
        for i in range(prompt, LENGTH):
            logits, past = model.step(idx[:, i:i + 1], past)
            cached.append(logits)
        full = [model(idx[:, :i])[0] for i in range(prompt, LENGTH + 1)]
    for a, b in zip(cached, full, strict=True):
        torch.testing.assert_close(a, b, rtol=1e-4, atol=1e-5)


def test_answer_stops_at_end_or_window(model):
    sampler = sampling.Sampler(model, end=0, bf16=False)
    opts = Sampling(temperature=1.0, top_k=0)
    torch.manual_seed(1)
    for ids in sampler.answer(torch.randint(1, VOCAB, (4, 5)), opts):
        assert ids[-1] == 0 or 5 - 1 + len(ids) == TINY.block
        assert 0 not in ids[:-1]


@pytest.fixture
def checkpoint(tmp_path, cfg):
    return tiny_model.save(tmp_path / "model.pt", cfg)


def _settings(cfg, path):
    return cfg.models.layout.model_copy(update={"checkpoint": path, "device": Device.CPU})


def test_layout_prompt_ends_with_answer_mark(checkpoint, cfg, lay_out):
    """`<answer>` в корпусе — первый токен ответа: без него модель продолжает условие."""
    model = layout.load(_settings(cfg, checkpoint))
    bare = tokens.bare(lay_out())
    prompt = model.prompt(bare, Mode.WITH_OPENINGS, cfg)[0].tolist()
    assert [model.words[i] for i in prompt] == [
        *tokens.condition(bare, Mode.WITH_OPENINGS, cfg), Mark.ANSWER]
    with pytest.raises(TokenError):  # необученная модель отвечает мусором
        model.answer(model.prompt(bare, Mode.WITH_OPENINGS, cfg), bare, 0, cfg)


def test_layout_refuses_model_with_other_vocabulary(checkpoint, cfg, lay_out):
    data = torch.load(checkpoint, weights_only=True)
    torch.save(data | {"vocabulary": [*data["vocabulary"][:-1], "lost"]}, checkpoint)
    model = layout.load(_settings(cfg, checkpoint))
    with pytest.raises(ModelError, match="словарь модели"):
        model.prompt(tokens.bare(lay_out()), Mode.WITH_OPENINGS, cfg)
