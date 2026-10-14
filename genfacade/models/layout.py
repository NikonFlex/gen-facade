"""Модель шага 4 — GPT, обученный `genfacade train` (gf#106), на месте стаба (gf#107).

Весь дом — одна последовательность (train/tokens.py): условие из параметров дома и сторон плана
→ ответ модели → `tokens.decode` → стены с элементами и зонами. Негодный ответ отбраковывает
конвейер и просит новый (pipeline.py, `generation: Брак — заново`).
"""

from pathlib import Path

import torch

from genfacade.config import Config, GPTSize, LayoutModel
from genfacade.models.stub import ModelError
from genfacade.schema import FacadeSheet, Mode
from genfacade.train import sampling, tokens
from genfacade.train.tokens import Mark, TokenError


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

    def prompt(self, bare: FacadeSheet, mode: Mode, cfg: Config) -> torch.Tensor:
        """Условие номерами токенов. Дом, который модель не может прочесть, — ModelError: это
        не брак ответа, повтор не поможет."""
        if self.words != tokens.vocabulary(cfg):
            raise ModelError(f"словарь модели {self.path} не совпадает с нынешней записью "
                             "токенов: модель учили на другой версии — переобучить")
        try:  # `<answer>` в корпусе — первый токен ответа: с него модель начинает отвечать
            words = [*tokens.condition(bare, mode, cfg), Mark.ANSWER]
            return torch.tensor([[self.number[t] for t in words]])
        except TokenError as e:
            raise ModelError(f"дом не записывается условием модели: {e}") from e

    def answer(self, prompt: torch.Tensor, bare: FacadeSheet, seed: int,
               cfg: Config) -> FacadeSheet:
        """Стены после развёртки → стены с элементами и зонами; ответ не разобран — TokenError."""
        torch.manual_seed(seed)
        ids = self.sampler.answer(prompt, cfg.models.layout)[0]
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
