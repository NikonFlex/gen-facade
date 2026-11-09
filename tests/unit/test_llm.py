"""Базовый подход «LLM без дообучения» на заглушке, без сети (gf#162): промпт, разбор ответа,
отказ на неразборном ответе, `--dry-run`, весь путь до таблицы `realtest`. Платный вызов в тестах
невозможен: клиент — заглушка или лист заранее записанных ответов."""

import json

import pytest

from genfacade import llm
from genfacade.metrics import realtest
from genfacade.models.stub import ModelError
from genfacade.schema import ElementClass, LlmProvider, Mode, Refusal
from genfacade.train import tokens
from genfacade.train.tokens import Answer, TokenError, bare, given_sides


class Canned:
    """Клиент, отвечающий одним текстом, и счёт запросов."""

    def __init__(self, text: str):
        self.text, self.calls = text, 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return self.text


@pytest.fixture
def pool(house):
    return llm.Pool([llm.shot(house)])


@pytest.fixture
def stub_model(house, cfg, pool):
    replies = llm.stub_replies(bare(house), Mode.WITH_OPENINGS, cfg)
    return llm.LlmLayout(LlmProvider.STUB, llm.StubClient(replies, cfg.baselines.llm), pool)


def test_prompt_has_description_mode_condition_and_examples(house, cfg, pool):
    sheet = bare(given_sides(house, Mode.BLIND))
    text = llm.build_prompt(sheet, Mode.BLIND, pool.nearest(sheet, Mode.BLIND, cfg), cfg)
    words = cfg.baselines.llm.prompt
    assert words.mode[Mode.BLIND] in text and words.mode[Mode.WITH_OPENINGS] not in text
    assert llm.describe(sheet, Mode.BLIND, cfg.baselines.llm) in text
    assert llm.record(tokens.condition(sheet, Mode.BLIND, cfg)) in text
    assert words.example.format(n=1) in text and text.endswith(words.answer)
    assert llm.condition_of(text, words.condition) == llm.record(
        tokens.condition(sheet, Mode.BLIND, cfg))


def test_stub_reply_parses_to_wall_elements(house, cfg, stub_model):
    walls = bare(house)
    prompt = stub_model.prompt(walls, Mode.WITH_OPENINGS, cfg)
    [got] = stub_model.answers(prompt, walls, 0, cfg, 1)
    assert isinstance(got, Answer)
    assert any(e.cls is ElementClass.WINDOW for f in got.sheet.facades for e in f.elements)


def test_reply_with_prose_and_fences_is_read(house, cfg):
    words = tokens.answer(house, Mode.WITH_OPENINGS, cfg)
    text = "Вот ответ:\n```\n" + llm.record(words) + "\n```\nНадеюсь, помог."
    assert llm.reply_words(text) == words


@pytest.mark.parametrize("text", ["не знаю", "<answer> <types> 9 <end>", ""])
def test_unreadable_reply_is_a_token_error(house, cfg, pool, text):
    model = llm.LlmLayout(LlmProvider.STUB, Canned(text), pool)
    walls = bare(house)
    [got] = model.answers("", walls, 0, cfg, 1)
    assert isinstance(got, TokenError)


def test_unreadable_reply_is_a_refusal_after_attempts(house, cfg, pool, tmp_path):
    api = Canned("не знаю")
    model = llm.LlmLayout(LlmProvider.STUB, api, pool)
    run_cfg = llm.tried(cfg)
    realtest.answers({"h": given_sides(house, Mode.BLIND)}, Mode.BLIND, run_cfg, tmp_path, model)
    got = json.loads((tmp_path / "h.json").read_text())
    assert got[realtest.REFUSED]["code"] == Refusal.MODEL_NO_ANSWER
    assert len(got["attempts"]) == api.calls == cfg.baselines.llm.attempts


def test_dry_run_counts_requests_and_money(real, cfg, pool, monkeypatch):
    monkeypatch.setattr(llm.Pool, "load", lambda _: pool)
    work = llm.load(cfg, 0)
    assert work.requests == len(real) * len(Mode) and work.refused == 0
    table = llm.dry_run(list(LlmProvider), cfg, 0)
    assert f"| claude | {cfg.baselines.llm.providers[LlmProvider.CLAUDE].model} | " \
           f"{work.requests} |" in table
    paid = [r for r in table.splitlines() if r.startswith("| claude")][0].split("|")
    assert float(paid[6]) > 0 and float([r for r in table.splitlines()
                                         if r.startswith("| stub")][0].split("|")[6]) == 0


def test_client_without_library_or_key_is_a_refusal(cfg, monkeypatch):
    monkeypatch.setattr(llm, "find_spec", lambda name: None)
    with pytest.raises(ModelError, match="нет библиотеки") as e:
        llm.client(LlmProvider.CLAUDE, {}, cfg)
    assert e.value.code is Refusal.LLM_UNAVAILABLE
    monkeypatch.setattr(llm, "find_spec", lambda name: object())
    monkeypatch.delenv(cfg.baselines.llm.providers[LlmProvider.DEEPSEEK].key_env, raising=False)
    with pytest.raises(ModelError, match="нет ключа"):
        llm.client(LlmProvider.DEEPSEEK, {}, cfg)


def test_stub_path_reaches_the_realtest_table(real, cfg, pool, monkeypatch, tmp_path):
    monkeypatch.setattr(llm.Pool, "load", lambda _: pool)
    folder = llm.run(LlmProvider.STUB, cfg, tmp_path / "llm", 0)
    for mode in Mode:
        assert {p.stem for p in (folder / mode / "model").glob("*.json")} == set(real)
        assert len(list((folder / mode / "calls").glob("*.json"))) == len(real)
    llm.run(LlmProvider.STUB, cfg, tmp_path / "llm", 0)  # готовые дома не пересчитываются
    assert len(list((folder / Mode.BLIND / "calls").glob("*.json"))) == len(real)
    realtest.run(cfg, tmp_path / "rt", 0, realtest.Rows({}, {"llm-stub": folder}))
    assert "model-llm-stub" in (tmp_path / "rt" / realtest.SUMMARY).read_text()
