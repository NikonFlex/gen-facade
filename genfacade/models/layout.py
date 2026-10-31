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
from genfacade.train.tokens import Answer, Mark, TokenError


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
        except TokenError as e:
            raise ModelError(f"дом не записывается условием модели: {e}") from e
        block = self.sampler.model.config.block_size
        if len(words) >= block:  # на ответ не осталось ни токена: повтор не поможет
            raise ModelError(f"условие дома — {len(words)} токенов, окно модели — {block}")
        return Condition([self.number[t] for t in words], mode)

    def answer(self, prompt: Condition, bare: FacadeSheet, seed: int, cfg: Config) -> Answer:
        """Стены после развёртки → стены с элементами и зонами; ответ не разобран — TokenError.
        С `constrain` рамка элемента не ломается (gf#177), а в глухом режиме окна не заходят в
        запретные зоны и на проёмы (gf#132)."""
        got = self.answers(prompt, bare, seed, cfg, 1)[0]
        if isinstance(got, TokenError):
            raise got
        return got

    def answers(self, prompt: Condition, bare: FacadeSheet, seed: int, cfg: Config,
                n: int) -> list[Answer | TokenError]:
        """n ответов одной пачкой, у каждого свой страж; неразобранный — TokenError на его месте.
        Пачка — ради «лучшего из N» (gf#213): на процессоре best_of = 16 — в среднем 36 с на дом
        при 8 с на один ответ, а не 16 × 8 (`docs/metrics-results.md`, раздел gf#213)."""
        guards = [self._guard(bare, prompt.mode, cfg) for _ in range(n)]
        torch.manual_seed(seed)
        ids = sampling.answer_all(self.sampler, [sampling.Prompt(prompt.ids, g) for g in guards],
                                  cfg.models.layout, batch=n)
        return [self._tried(i, bare, cfg) for i in ids]

    def _tried(self, ids: list[int], bare: FacadeSheet, cfg: Config) -> Answer | TokenError:
        try:
            return self._decoded(ids, bare, cfg)
        except TokenError as e:
            return e

    def redo(self, prompt: Condition, bare: FacadeSheet, old: Answer, wall: int,
             seed: int, cfg: Config) -> Answer:
        """Тот же ответ, но стена номер wall — заново (gf#213): слова до её `<wall>` и после
        следующего `<wall>` (у последней стены — `<end>`) не меняются, страж читает префикс и
        знает уже поставленное."""
        ids = [self.number[w] for w in old.words]
        walls = [i for i, t in enumerate(ids) if t == self.vocab.wall]
        head = walls[wall] + 1  # с `<wall>` плохой стены: дальше — только её элементы
        tail = walls[wall + 1] if wall + 1 < len(walls) else ids.index(self.vocab.end)
        guard = self._guard(bare, prompt.mode, cfg)
        for t in ids[1:head] if guard is not None else []:
            guard.step(t)
        torch.manual_seed(seed)
        prefix = torch.tensor([prompt.ids[:-1] + ids[:head]], dtype=torch.long)
        stops = frozenset({self.vocab.wall, self.vocab.end})
        new = self.sampler.answer(prefix, cfg.models.layout, [guard], stops)[0][1:]
        if new and new[-1] in stops:  # стена кончилась — дальше прежние; иначе оборвана окном
            new = new[:-1] + ids[tail:]
        return self._decoded(ids[:head] + new, bare, cfg)

    def _guard(self, bare: FacadeSheet, mode: Mode, cfg: Config):
        on = cfg.models.layout.constrain
        return constraints.guard(bare, mode, self.vocab, cfg) if on else None

    def _decoded(self, ids: list[int], bare: FacadeSheet, cfg: Config) -> Answer:
        words = [self.words[i] for i in ids]
        return Answer(words, tokens.decode(words, bare, cfg))


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
