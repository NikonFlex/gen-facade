"""Модель шага 4 — GPT, обученный `genfacade train` (gf#106), на месте стаба (gf#107).

Весь дом — одна последовательность (train/tokens.py): условие из параметров дома и сторон плана
→ ответ модели → `tokens.decode` → стены с элементами и зонами. Негодный ответ отбраковывает
конвейер и просит новый (pipeline.py, `generation: Брак — заново`).
"""

from pathlib import Path
from typing import NamedTuple

import torch

from genfacade.config import Config, GPTSize, LayoutModel
from genfacade.models.stub import ModelError
from genfacade.schema import FacadeSheet, Mode
from genfacade.train import constraints, sampling, tokens
from genfacade.train.tokens import Mark, TokenError


class Condition(NamedTuple):
    """Условие дома: номера токенов до `<answer>` включительно и режим — по нему страж решает,
    запрещать ли окна при генерации."""

    ids: list[int]
    mode: Mode


class Layout:
    """Обученная модель на своём устройстве и словарь, с которым её учили."""

    def __init__(self, path: Path, settings: LayoutModel):
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
        self.path, self.words = path, list(checkpoint["vocabulary"])
        model = sampling.build_model(GPTSize(**checkpoint["size"]), len(self.words))
        model.load_state_dict(checkpoint["model"])
        model.to(sampling.device(settings.device))
        self.sampler = sampling.Sampler(model, self.words.index(Mark.END), settings.bf16)
        self.number = {w: i for i, w in enumerate(self.words)}
        self.vocab = constraints.Vocab(self.words)

    def prompt(self, bare: FacadeSheet, mode: Mode, cfg: Config) -> Condition:
        """Условие номерами токенов. Дом, который модель не может прочесть, — ModelError: это
        не брак ответа, повтор не поможет."""
        if self.words != tokens.vocabulary(cfg):
            raise ModelError(f"словарь модели {self.path} не совпадает с нынешней записью "
                             "токенов: модель учили на другой версии — переобучить")
        try:  # `<answer>` в корпусе — первый токен ответа: с него модель начинает отвечать
            words = [*tokens.condition(bare, mode, cfg), Mark.ANSWER]
            return Condition([self.number[t] for t in words], mode)
        except TokenError as e:
            raise ModelError(f"дом не записывается условием модели: {e}") from e

    def answer(self, prompt: Condition, bare: FacadeSheet, seed: int,
               cfg: Config) -> FacadeSheet:
        """Стены после развёртки → стены с элементами и зонами; ответ не разобран — TokenError.
        С `constrain` в глухом режиме окна не заходят в запретные зоны и на проёмы (gf#132)."""
        on = cfg.models.layout.constrain
        guard = constraints.guard(bare, prompt.mode, self.vocab, cfg) if on else None
        torch.manual_seed(seed)
        ids = sampling.answer_all(self.sampler, [sampling.Prompt(prompt.ids, guard)],
                                  cfg.models.layout, batch=1)[0]
        return tokens.decode([self.words[i] for i in ids], bare, cfg)


_loaded: dict[tuple, Layout] = {}


def load(settings: LayoutModel) -> Layout:
    """Модель грузится один раз на процесс — смотрелка строит фасады подряд; заменили файл
    или устройство — грузится заново."""
    path = settings.checkpoint.resolve()
    key = (path, path.stat().st_mtime_ns, settings.device, settings.bf16)
    if key not in _loaded:
        _loaded.clear()
        _loaded[key] = Layout(path, settings)
    return _loaded[key]
