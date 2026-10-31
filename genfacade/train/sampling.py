"""Ответ модели шага 4 на условие — токен за токеном до `<end>`.

Общий для проверки после обучения (train/fit.py, gf#106) и конвейера (models/layout.py, gf#107).
Сэмплирование — как `generate` в nanoGPT (температура, top-k), но с KV-кэшем и остановкой на
`<end>`.
"""

from typing import NamedTuple, Protocol

import torch

from genfacade.config import GPTSize, Sampling
from genfacade.schema import Device
from genfacade.train.gpt import GPT, GPTConfig


def device(choice: Device) -> torch.device:
    if choice is Device.AUTO:
        return torch.device(Device.CUDA if torch.cuda.is_available() else Device.CPU)
    return torch.device(choice)


def build_model(size: GPTSize, vocabulary: int) -> GPT:
    return GPT(GPTConfig(block_size=size.block, vocab_size=vocabulary, n_layer=size.layers,
                         n_head=size.heads, n_embd=size.width, dropout=size.dropout))


class Guard(Protocol):
    """Страж одного ответа: читает выбранные токены и называет запрещённые следующим."""

    def step(self, token: int) -> None: ...

    def banned(self) -> list[int]: ...


class Prompt(NamedTuple):
    """Условие до `<answer>` включительно и, если надо, страж ответа на него."""

    ids: list[int]
    guard: Guard | None = None


class Sampler:
    """Модель на своём устройстве: прямой проход (на GPU — в bfloat16) и дописывание ответа."""

    def __init__(self, model: GPT, end: int, bf16: bool):
        self.model, self.end = model, end
        self.device = next(model.parameters()).device
        self.bf16 = bf16 and self.device.type == Device.CUDA

    def autocast(self):
        return torch.autocast(self.device.type, dtype=torch.bfloat16, enabled=self.bf16)

    @torch.no_grad()
    def answer(self, prompts: torch.Tensor, opts: Sampling,
               guards: list[Guard | None] | None = None,
               stops: frozenset[int] | None = None) -> list[list[int]]:
        """Дописывать токены, пока у всех не будет стопового (по умолчанию `<end>`) или не
        кончится окно; вернуть ответы от последнего токена условия (`<answer>`) до стопового
        включительно. Стоп `<wall>` — досэмплировать одну стену (gf#213). Условия в пачке —
        одной длины: позиции в nanoGPT абсолютные, паддинг слева их бы сдвинул. Прошлые
        позиции не пересчитываются — KV-кэш (`GPT.step`)."""
        self.model.eval()
        stops = stops or frozenset({self.end})
        stop = torch.tensor(sorted(stops), device=self.device)
        idx = prompts.to(self.device)
        done = torch.zeros(len(idx), dtype=torch.bool, device=self.device)
        start = idx.size(1) - 1
        with self.autocast():
            logits, past = self.model.step(idx)
        while True:
            nxt = _pick(_forbid(logits[:, -1, :].float(), guards), opts)
            _observe(guards, nxt)
            idx = torch.cat((idx, nxt), dim=1)
            done |= torch.isin(nxt.squeeze(1), stop)
            if done.all() or idx.size(1) >= self.model.config.block_size:
                break
            with self.autocast():
                logits, past = self.model.step(nxt, past)
        return [_cut(row[start:].tolist(), stops) for row in idx]


def answer_all(sampler: Sampler, prompts: list[Prompt], opts: Sampling,
               batch: int) -> list[list[int]]:
    """Ответы на много условий: пачками до batch условий одной длины (`Sampler.answer`),
    в том же порядке, что prompts."""
    by_length: dict[int, list[int]] = {}
    for i, p in enumerate(prompts):
        by_length.setdefault(len(p.ids), []).append(i)
    answers: list[list[int]] = [[] for _ in prompts]
    for rows in by_length.values():
        for start in range(0, len(rows), batch):
            group = rows[start:start + batch]
            stacked = torch.tensor([prompts[i].ids for i in group], dtype=torch.long)
            guards = [prompts[i].guard for i in group]
            for i, ids in zip(group, sampler.answer(stacked, opts, guards), strict=True):
                answers[i] = ids
    return answers


def _forbid(logits: torch.Tensor, guards: list[Guard | None] | None) -> torch.Tensor:
    """Запрещённые стражами токены — логиты −∞: их вероятность ноль."""
    for row, g in enumerate(guards or []):
        if g is not None and (banned := g.banned()):
            logits[row, banned] = -float("inf")
    return logits


def _observe(guards: list[Guard | None] | None, nxt: torch.Tensor) -> None:
    for row, g in enumerate(guards or []):
        if g is not None:
            g.step(int(nxt[row, 0]))


def _pick(logits: torch.Tensor, opts: Sampling) -> torch.Tensor:
    """Следующий токен: температура, top-k, случайный выбор по вероятностям — как в nanoGPT."""
    logits = logits / opts.temperature
    if opts.top_k:
        v, _ = torch.topk(logits, min(opts.top_k, logits.size(-1)))
        logits[logits < v[:, [-1]]] = -float("inf")
    return torch.multinomial(torch.softmax(logits, dim=-1), num_samples=1)


def _cut(ids: list[int], stops: frozenset[int]) -> list[int]:
    """До первого стопового после токена условия: сам он (`<wall>` стены, которую
    досэмплируют) — не стоп."""
    at = next((i for i, t in enumerate(ids) if i and t in stops), None)
    return ids if at is None else ids[:at + 1]
