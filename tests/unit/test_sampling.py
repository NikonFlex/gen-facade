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

# долгий: torch — вне быстрой проверки перед коммитом (gf#165)
pytestmark = pytest.mark.slow

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


def test_answer_stops_at_any_given_token(model):
    """Стоп — любой из заданных токенов (`<wall>` — досэмплировать одну стену, gf#213): после
    него страж токенов не видит; токен условия, на котором ответ начинается, — не стоп."""
    sampler = sampling.Sampler(model, end=0, bf16=False)
    torch.manual_seed(1)
    stops, guards = frozenset({1, 2}), [_Ban([])]
    prompt = torch.tensor([[3, 4, 5, 6, 1]])
    ids = sampler.answer(prompt, Sampling(temperature=1.0, top_k=0), guards, stops)[0]
    assert ids[-1] in stops and not stops & set(ids[1:-1])
    assert guards[0].seen == ids[1:]                 # дальше стопа не сэмплировал


@pytest.fixture
def checkpoint(tmp_path, cfg):
    return tiny_model.save(tmp_path / "model.pt", cfg)


def _settings(cfg, path):
    return cfg.models.layout.model_copy(update={"checkpoint": path, "device": Device.CPU})


def test_layout_prompt_ends_with_answer_mark(checkpoint, cfg, lay_out):
    """`<answer>` в корпусе — первый токен ответа: без него модель продолжает условие."""
    model = layout.load(_settings(cfg, checkpoint))
    bare = tokens.bare(lay_out())
    prompt = model.prompt(bare, Mode.WITH_OPENINGS, cfg).ids
    assert [model.words[i] for i in prompt] == [
        *tokens.condition(bare, Mode.WITH_OPENINGS, cfg), Mark.ANSWER]


@pytest.mark.parametrize("constrain", [False, True])
def test_guard_makes_untrained_answer_readable(checkpoint, cfg, lay_out, constrain):
    """Необученная модель без стража отвечает мусором; страж (gf#177, gf#197) держит грамматику
    ответа — тот же ответ разбирается в лист (gf#208)."""
    settings = _settings(cfg, checkpoint).model_copy(update={"constrain": constrain})
    run = cfg.model_copy(update={"models": cfg.models.model_copy(update={"layout": settings})})
    model = layout.load(settings)
    bare = tokens.bare(lay_out())
    prompt = model.prompt(bare, Mode.WITH_OPENINGS, run)
    if not constrain:
        with pytest.raises(TokenError):
            model.answer(prompt, bare, 0, run)
    else:
        sheet = model.answer(prompt, bare, 0, run).sheet
        assert len(sheet.facades) == len(bare.facades)


@pytest.fixture
def asked(checkpoint, cfg, lay_out):
    """Крошечная модель, простой дом после развёртки и условие на него."""
    model = layout.load(_settings(cfg, checkpoint))
    bare = tokens.bare(lay_out())
    return model, bare, model.prompt(bare, Mode.WITH_OPENINGS, cfg)


def test_answers_in_one_batch_each_with_own_guard(asked, cfg):
    """Пачка ответов для «лучшего из N» (gf#213): у каждого свой страж — каждый разбирается;
    ответы разные; пачка из одного — тот же ответ, что `answer`."""
    model, bare, prompt = asked
    many = model.answers(prompt, bare, 0, cfg, 3)
    assert all(len(a.sheet.facades) == len(bare.facades) for a in many)
    assert len({tuple(a.words) for a in many}) == 3
    assert model.answers(prompt, bare, 5, cfg, 1)[0] == model.answer(prompt, bare, 5, cfg)


def test_redo_changes_only_its_wall(asked, cfg):
    """Перегенерация одной стены (gf#213): слова до её `<wall>` и после неё — прежние, остальные
    стены дома не меняются, а она — сэмплирована заново."""
    model, bare, prompt = asked
    old = model.answer(prompt, bare, 0, cfg)
    for wall in range(len(bare.facades)):
        new = model.redo(prompt, bare, old, wall, 1, cfg)
        same = [a == b for a, b in zip(old.sheet.facades, new.sheet.facades, strict=True)]
        assert same == [i != wall for i in range(len(same))]


def test_layout_refuses_model_with_other_vocabulary(checkpoint, cfg, lay_out):
    data = torch.load(checkpoint, weights_only=True)
    torch.save(data | {"vocabulary": [*data["vocabulary"][:-1], "lost"]}, checkpoint)
    model = layout.load(_settings(cfg, checkpoint))
    with pytest.raises(ModelError, match="словарь модели"):
        model.prompt(tokens.bare(lay_out()), Mode.WITH_OPENINGS, cfg)


def test_layout_refuses_prompt_longer_than_window(checkpoint, cfg, lay_out):
    """Условие дома не помещается в окно модели — отказ с причиной, а не падение прохода
    модели посреди прогона и не обрезанный ответ (новая запись токенов длиннее, gf#212)."""
    data = torch.load(checkpoint, weights_only=True)
    short = TINY.model_copy(update={"block": 8})
    model = sampling.build_model(short, len(data["vocabulary"]))
    torch.save(data | {"model": model.state_dict(), "size": short.model_dump()}, checkpoint)
    with pytest.raises(ModelError, match="окно модели — 8"):
        layout.load(_settings(cfg, checkpoint)).prompt(tokens.bare(lay_out()),
                                                       Mode.WITH_OPENINGS, cfg)


class _Ban:
    """Страж, запрещающий одни и те же токены на каждом шаге."""

    def __init__(self, ids):
        self.ids, self.seen = list(ids), []

    def step(self, token):
        self.seen.append(token)

    def banned(self):
        return self.ids


def test_guarded_tokens_are_never_picked(model):
    sampler = sampling.Sampler(model, end=0, bf16=False)
    guards = [_Ban(range(1, 6)), None]
    torch.manual_seed(2)
    prompts = [sampling.Prompt([7, 8, 9], g) for g in guards]
    guarded, free = sampling.answer_all(sampler, prompts, Sampling(temperature=1.0, top_k=0), 2)
    assert not set(guarded[1:]) & set(range(1, 6))
    assert guards[0].seen == guarded[1:]        # страж видел все выбранные токены, по порядку
    assert set(free[1:]) & set(range(1, 6))     # без стража те же токены выпадают
