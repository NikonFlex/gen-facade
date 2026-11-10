"""Базовый подход «LLM без дообучения» (gf#162, `evaluation: Базовые подходы`).

LLM получает дом той же записью токенов, что наша модель шага 4 (`train/tokens.py`): ответ в
4–5 раз короче JSON листа, а разбор (`tokens.decode`), привязка и валидатор — те же шаги 4–5
конвейера (`pipeline.layout`), поэтому сравнение честное. Промпт: правила записи, k примеров
из синтетики (ближайшие по числу сторон, этажей и периметру, тот же режим), дом и его условие.
Дом из частей разной высоты отвечает по частям, как модель.

    <out>/<поставщик>/<режим>/model/<дом>.json   лист или {"refusal": …, "attempts": …}
    <out>/<поставщик>/<режим>/calls/<дом>-<n>.json   каждый запрос: промпт, ответ, оценка токенов

Папка `<out>/<поставщик>` читается `genfacade realtest --sheets llm-<поставщик>=<папка>`. Дом,
чей лист уже лежит в папке, не пересчитывается: оборванный прогон продолжается, а платный
запрос не повторяется. Тесты и `stub` в сеть не ходят; ключ — из переменной окружения.
"""

import json
import math
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path
from typing import NamedTuple, Protocol

import numpy
from pydantic import ValidationError

from genfacade import baselines, parts
from genfacade.config import Config, Llm, LlmEndpoint
from genfacade.datasets import store
from genfacade.metrics import calibrate, realtest
from genfacade.models.stub import ModelError
from genfacade.schema import FacadeSheet, LlmProvider, Mode, Refusal, Source, Split
from genfacade.train import tokens
from genfacade.train.tokens import Answer, TokenError, bare, given_sides

MILLION = 1_000_000
FENCE = "```"


class Client(Protocol):
    """Вызов модели: промпт → текст ответа. Больше от поставщика ничего не нужно."""

    def complete(self, prompt: str) -> str: ...


# ——— клиенты ———

class StubClient:
    """Заранее записанные ответы: промпт → ответ по условию дома, без сети. Нет записи —
    отказ, а не пустой ответ."""

    def __init__(self, replies: dict[str, str], cfg: Llm):
        self.replies, self.marker = replies, cfg.prompt.condition

    def complete(self, prompt: str) -> str:
        key = condition_of(prompt, self.marker)
        if key not in self.replies:
            raise ModelError(Refusal.LLM_UNAVAILABLE, "у заглушки нет записанного ответа")
        return self.replies[key]


def request(endpoint: LlmEndpoint, cfg: Llm, prompt: str) -> dict:
    """Параметры запроса, общие у обеих библиотек."""
    return {"model": endpoint.model, "max_tokens": cfg.max_output_tokens,
            "temperature": cfg.temperature, "messages": [{"role": "user", "content": prompt}]}


class ApiClient:
    """Запрос поставщику через его библиотеку: параметры — `request`, ожидание — `timeout_s`.
    Наследник знает, как подключиться, куда послать запрос и где в ответе текст."""

    def __init__(self, endpoint: LlmEndpoint, key: str, cfg: Llm):
        self.endpoint, self.cfg = endpoint, cfg
        self.api = self.connect(key)

    def complete(self, prompt: str) -> str:
        return self.text(self.send(request(self.endpoint, self.cfg, prompt)))

    def connect(self, key: str):
        raise NotImplementedError

    def send(self, params: dict):
        raise NotImplementedError

    def text(self, reply) -> str:
        raise NotImplementedError


class AnthropicClient(ApiClient):
    def connect(self, key: str):
        import anthropic  # noqa: PLC0415 — библиотеки нет в группах проекта: ставит хозяин

        return anthropic.Anthropic(api_key=key, timeout=self.cfg.timeout_s, max_retries=0)

    def send(self, params: dict):
        return self.api.messages.create(**params)

    def text(self, reply) -> str:
        return "".join(b.text for b in reply.content if b.type == "text")


class OpenAIClient(ApiClient):
    """OpenAI и совместимые (DeepSeek — `base_url` из конфига)."""

    def connect(self, key: str):
        import openai  # noqa: PLC0415 — см. AnthropicClient

        return openai.OpenAI(api_key=key, base_url=self.endpoint.base_url,
                             timeout=self.cfg.timeout_s, max_retries=0)

    def send(self, params: dict):
        return self.api.chat.completions.create(**params)

    def text(self, reply) -> str:
        return reply.choices[0].message.content or ""


# Библиотека и клиент поставщика: DeepSeek говорит по OpenAI-совместимому API.
LIBRARY = {LlmProvider.CLAUDE: ("anthropic", AnthropicClient),
           LlmProvider.OPENAI: ("openai", OpenAIClient),
           LlmProvider.DEEPSEEK: ("openai", OpenAIClient)}


def client(provider: LlmProvider, replies: dict[str, str], cfg: Config) -> Client:
    """Клиент поставщика. Нет библиотеки или ключа в окружении — отказ сразу, до первой работы:
    библиотеки не ставим сами, ключ — из переменной окружения по имени из конфига."""
    llm = cfg.baselines.llm
    if provider is LlmProvider.STUB:
        return StubClient(replies, llm)
    library, make = LIBRARY[provider]
    endpoint = llm.providers[provider]
    if find_spec(library) is None:
        raise ModelError(Refusal.LLM_UNAVAILABLE,
                         f"{provider}: нет библиотеки {library} в окружении проекта")
    key = os.environ.get(endpoint.key_env or "")
    if not key:
        raise ModelError(Refusal.LLM_UNAVAILABLE,
                         f"{provider}: нет ключа в переменной окружения {endpoint.key_env}")
    return make(endpoint, key, llm)


# ——— оценка токенов и цены ———

def estimate_tokens(text: str, cfg: Llm) -> int:
    return math.ceil(len(text) / cfg.chars_per_token)


def price(tokens_in: int, tokens_out: int, endpoint: LlmEndpoint) -> float:
    return (tokens_in * endpoint.usd_per_mtok_in + tokens_out * endpoint.usd_per_mtok_out) / MILLION


@dataclass
class Recorded:
    """Клиент с записью каждого входа и выхода (хозяин 02.11): файл `<дом>-<n>.json` на запрос.
    `label` — дом, который сейчас отвечает."""

    inner: Client
    folder: Path
    cfg: Llm
    label: str = ""
    count: int = 0

    def complete(self, prompt: str) -> str:
        reply = self.inner.complete(prompt)
        self.count += 1
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{self.label}-{self.count}.json").write_text(json.dumps({
            "date": datetime.now().astimezone().isoformat(timespec="seconds"),
            "prompt": prompt, "reply": reply, "estimated": True,
            "tokens_in": estimate_tokens(prompt, self.cfg),
            "tokens_out": estimate_tokens(reply, self.cfg)}, ensure_ascii=False, indent=1))
        return reply


# ——— промпт ———

class Shot(NamedTuple):
    sheet: FacadeSheet
    sides: int
    perimeter: float


class Pool:
    """Дома синтетики train, из которых берутся примеры. Реальные дома сюда не входят — это
    утечка эталона."""

    def __init__(self, shots: list[Shot]):
        self.shots = shots

    @classmethod
    def load(cls, cfg: Config) -> "Pool":
        """pool домов train, выбранных по seed из всей синтетики."""
        llm, root = cfg.baselines.llm, cfg.data.paths.samples_dir
        ids = store.ids(root, Source.SYNTHETIC)
        shots: list[Shot] = []
        for i in numpy.random.default_rng(llm.seed).permutation(len(ids)):
            sample = store.read(root, Source.SYNTHETIC, ids[i])
            if sample.split is Split.TRAIN:
                shots.append(shot(sample.sheet))
            if len(shots) >= llm.pool:
                break
        return cls(shots)

    def nearest(self, house: FacadeSheet, mode: Mode, cfg: Config) -> list[FacadeSheet]:
        """Ближайшие по числу сторон, затем этажей, затем периметру; пример, который не
        записывается токенами в этом режиме, пропускается."""
        want = shot(house)
        near = sorted(self.shots, key=lambda s: (abs(s.sides - want.sides),
                                                 abs(s.sheet.spec.floors - house.spec.floors),
                                                 abs(s.perimeter - want.perimeter)))
        out: list[FacadeSheet] = []
        for s in near:
            if len(out) >= cfg.baselines.llm.shots:
                break
            try:
                tokens.encode(s.sheet, mode, cfg)
            except TokenError:
                continue
            out.append(s.sheet)
        return out


def shot(sheet: FacadeSheet) -> Shot:
    return Shot(sheet, len(sheet.facades), sum(f.side.length_m for f in sheet.facades))


def record(words: Iterable[str]) -> str:
    """Токены — строками для чтения: стена, элемент, зона — с новой строки."""
    return "\n".join(tokens.lines(list(words)))


def words_of(cfg: Config) -> str:
    """Служебные токены и слова записи — без чисел: числа модель берёт из примеров."""
    return " ".join(w for w in tokens.vocabulary(cfg) if not w.isdigit())


def describe(sheet: FacadeSheet, mode: Mode, cfg: Llm) -> str:
    """Дом словами: то, что в условии записано токенами, и условие режима."""
    spec = sheet.spec
    text = cfg.prompt.house.format(type=spec.building_type, floors=spec.floors,
                                   roof=spec.roof.kind, style=spec.style, sides=len(sheet.facades))
    return f"{text} {cfg.prompt.mode[mode]}"


def build_prompt(house: FacadeSheet, mode: Mode, examples: list[FacadeSheet], cfg: Config) -> str:
    llm = cfg.baselines.llm
    p = llm.prompt
    blocks = [instruction(cfg), p.vocabulary.format(words=words_of(cfg))]
    for n, s in enumerate(examples, start=1):
        blocks.append(f"{p.example.format(n=n)}\n{describe(s, mode, llm)}\n{p.condition}\n"
                      f"{record(tokens.condition(s, mode, cfg))}\n{p.answer}\n"
                      f"{record(tokens.answer(s, mode, cfg))}")
    blocks.append(f"{describe(house, mode, llm)}\n{p.condition}\n"
                  f"{record(tokens.condition(house, mode, cfg))}\n{p.answer}")
    return "\n\n".join(blocks)


def instruction(cfg: Config) -> str:
    return cfg.baselines.llm.prompt.instruction.format(grid_m=cfg.tokens.grid_m)


def condition_of(prompt: str, marker: str) -> str:
    """Условие дома, о котором спрашивает промпт: его последний блок."""
    return prompt.rsplit(marker, 1)[1].strip().rsplit("\n", 1)[0].strip()


def reply_words(text: str) -> list[str]:
    """Токены ответа: от `<answer>` до `<end>` включительно. Ограды ``` и слова вокруг записи
    отбрасываются; нет `<answer>` — слова как есть, и разбор откажет."""
    words = [w for w in text.replace(FENCE, " ").split()]
    start = words.index(tokens.Mark.ANSWER) if tokens.Mark.ANSWER in words else 0
    words = words[start:]
    if tokens.Mark.END in words:
        words = words[: words.index(tokens.Mark.END) + 1]
    return words


# ——— модель шагов 4–5 ———

class LlmLayout:
    """Интерфейс модели шага 4 (`prompt`, `answers`, `path`) поверх LLM: `pipeline.layout`
    повторяет её ответы и проверяет привязкой и валидатором, как ответы обученной модели."""

    def __init__(self, provider: LlmProvider, api: Client, pool: Pool):
        self.path, self.api, self.pool = Path(f"llm-{provider}"), api, pool

    def prompt(self, house: FacadeSheet, mode: Mode, cfg: Config) -> str:
        try:
            return build_prompt(house, mode, self.pool.nearest(house, mode, cfg), cfg)
        except TokenError as e:
            raise ModelError(Refusal.HOUSE_OUT_OF_MODEL,
                             f"дом не записывается условием: {e}") from e

    def answers(self, prompt: str, house: FacadeSheet, seed: int, cfg: Config,
                n: int) -> list[Answer | TokenError]:
        """n ответов: у каждого свой запрос (seed поставщику не передаётся — он не везде есть)."""
        return [self._tried(self.api.complete(prompt), house, cfg) for _ in range(n)]

    def _tried(self, text: str, house: FacadeSheet, cfg: Config) -> Answer | TokenError:
        words = reply_words(text)
        try:
            return Answer(words, tokens.decode(words, house, cfg))
        except TokenError as e:
            return TokenError(str(e), words, e.wall)
        except ValidationError as e:  # схема не приняла рамку: тоже брак ответа
            return TokenError(str(e).splitlines()[0], words)


# ——— заглушка ———

def units(house: FacadeSheet) -> list[FacadeSheet]:
    """На что отвечает модель: дом или его части одной этажности (gf#322)."""
    return [u for u, _ in parts.sub_sheets(house).values()] if parts.stepped(house) else [house]


def stub_replies(house: FacadeSheet, mode: Mode, cfg: Config) -> dict[str, str]:
    """Ответы заглушки на дом: что ответило бы правило GenPlan (`baselines.genplan`) —
    записью токенов. Это не эталон: заглушка проверяет путь до таблицы, а не ждёт хорошей строки.
    Часть дома, которую правило не записать токенами, остаётся без ответа."""
    out = {}
    for unit in units(house):
        try:
            out[record(tokens.condition(unit, mode, cfg))] = " ".join(
                tokens.answer(baselines.genplan(unit, cfg), mode, cfg))
        except TokenError:
            continue
    return out


# ——— прогон и оценка ———

def run(provider: LlmProvider, cfg: Config, out: Path, limit: int) -> Path:
    """Дома реального теста → ответы LLM → листы `<out>/<поставщик>/<режим>/model`."""
    real = calibrate.houses(Source.MANUAL, Split.TEST, limit, cfg)
    given = {m: {n: given_sides(s, m) for n, s in real.items()} for m in Mode}
    replies = {k: v for m in Mode for s in given[m].values()
               for k, v in stub_replies(bare(s), m, cfg).items()} \
        if provider is LlmProvider.STUB else {}
    api, pool, run_cfg = client(provider, replies, cfg), Pool.load(cfg), tried(cfg)
    folder = out / provider
    for mode in Mode:
        recorded = Recorded(api, folder / mode / "calls", cfg.baselines.llm)
        model = LlmLayout(provider, recorded, pool)
        for name, sheet in given[mode].items():
            if not (folder / mode / realtest.MODEL / f"{name}.json").exists():
                recorded.label = name
                realtest.answers({name: sheet}, mode, run_cfg, folder / mode / realtest.MODEL,
                                 model)
    return folder


def tried(cfg: Config) -> Config:
    """Настройки конвейера под LLM: попыток — из `[llm]`, один ответ за попытку, стены не
    досэмплируются (у LLM нет префикса, который можно продолжить)."""
    layout = cfg.models.layout.model_copy(update={
        "attempts": cfg.baselines.llm.attempts, "best_of": 1, "wall_retry": False,
        "seed": cfg.baselines.llm.seed})
    return cfg.model_copy(update={"models": cfg.models.model_copy(update={"layout": layout})})


class Load(NamedTuple):
    """Что отправит прогон, одинаково для всех поставщиков."""

    requests: int      # запросов, если все дома ответят с первой попытки
    tokens_in: int
    tokens_out: int
    refused: int       # «дом-режим», на который запроса не будет: дом не записывается токенами


def load(cfg: Config, limit: int) -> Load:
    """Промпты строятся как в настоящем прогоне, ответ оценивается длиной эталонного ответа дома
    той же записью (оценка, не замер)."""
    llm, pool = cfg.baselines.llm, Pool.load(cfg)
    real = calibrate.houses(Source.MANUAL, Split.TEST, limit, cfg)
    requests = refused = tokens_in = tokens_out = 0
    for mode in Mode:
        for sheet in real.values():
            given = given_sides(sheet, mode)
            try:
                prompts = [build_prompt(u, mode, pool.nearest(u, mode, cfg), cfg)
                           for u in units(bare(given))]
                gold = " ".join(tokens.answer(given, mode, cfg))
            except TokenError:
                refused += 1
                continue
            requests += len(prompts)
            tokens_in += sum(estimate_tokens(p, llm) for p in prompts)
            tokens_out += estimate_tokens(gold, llm)
    return Load(requests, tokens_in, tokens_out, refused)


def dry_run(providers: list[LlmProvider], cfg: Config, limit: int) -> str:
    """Таблица для хозяина до запуска: запросы, токены и цена по конфигу на каждого поставщика."""
    llm, work = cfg.baselines.llm, load(cfg, limit)
    lines = [f"| поставщик | модель | запросов | токенов на вход | токенов на выход | цена, $ | "
             f"цена при {llm.attempts} попытках на дом, $ |", "|---|---|---|---|---|---|---|"]
    for provider in providers:
        endpoint = llm.providers[provider]
        usd = price(work.tokens_in, work.tokens_out, endpoint)
        lines.append(f"| {provider} | {endpoint.model} | {work.requests} | {work.tokens_in} | "
                     f"{work.tokens_out} | {usd:.2f} | {usd * llm.attempts:.2f} |")
    lines.append(f"Домов без запроса (не записываются токенами): {work.refused}. Оценка: токенов — "
                 "знаков / chars_per_token; выход — длина эталонного ответа; запрос — дом × "
                 "режим, брак повторяется до attempts.")
    return "\n".join(lines)
