"""Ответ модели шага 4 на условие — токен за токеном до `<end>`.

Общий для проверки после обучения (train/fit.py, gf#106) и конвейера (models/layout.py, gf#107).
Сэмплирование — как `generate` в nanoGPT (температура, top-k), но с KV-кэшем и остановкой на
`<end>`.
"""

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


class Sampler:
    """Модель на своём устройстве: прямой проход (на GPU — в bfloat16) и дописывание ответа."""

    def __init__(self, model: GPT, end: int, bf16: bool):
        self.model, self.end = model, end
        self.device = next(model.parameters()).device
        self.bf16 = bf16 and self.device.type == Device.CUDA

    def autocast(self):
        return torch.autocast(self.device.type, dtype=torch.bfloat16, enabled=self.bf16)

    @torch.no_grad()
    def answer(self, prompts: torch.Tensor, opts: Sampling) -> list[list[int]]:
        """Дописывать токены, пока у всех не будет `<end>` или не кончится окно; вернуть ответы
        от `<answer>` — последнего токена условия — до `<end>` включительно. Условия в пачке —
        одной длины: позиции в nanoGPT абсолютные, паддинг слева их бы сдвинул. Прошлые
        позиции не пересчитываются — KV-кэш (`GPT.step`)."""
        self.model.eval()
        idx = prompts.to(self.device)
        done = torch.zeros(len(idx), dtype=torch.bool, device=self.device)
        start = idx.size(1) - 1
        with self.autocast():
            logits, past = self.model.step(idx)
        while True:
            nxt = _pick(logits[:, -1, :].float(), opts)
            idx = torch.cat((idx, nxt), dim=1)
            done |= nxt.squeeze(1) == self.end
            if done.all() or idx.size(1) >= self.model.config.block_size:
                break
            with self.autocast():
                logits, past = self.model.step(nxt, past)
        return [_cut(row[start:].tolist(), self.end) for row in idx]


def _pick(logits: torch.Tensor, opts: Sampling) -> torch.Tensor:
    """Следующий токен: температура, top-k, случайный выбор по вероятностям — как в nanoGPT."""
    logits = logits / opts.temperature
    if opts.top_k:
        v, _ = torch.topk(logits, min(opts.top_k, logits.size(-1)))
        logits[logits < v[:, [-1]]] = -float("inf")
    return torch.multinomial(torch.softmax(logits, dim=-1), num_samples=1)


def _cut(ids: list[int], end: int) -> list[int]:
    return ids[:ids.index(end) + 1] if end in ids else ids
