"""Крошечная необученная модель шага 4 со словарём нынешней записи токенов — для тестов модели
(test_sampling, test_evaluate). Импортируется только там, где torch есть (conftest.py)."""

from pathlib import Path

import torch

from genfacade.config import Config, GPTSize
from genfacade.train import sampling, tokens

SIZE = GPTSize(block=704, layers=1, heads=2, width=8, dropout=0.0)


def save(path: Path, cfg: Config) -> Path:
    words = tokens.vocabulary(cfg)
    torch.save({"model": sampling.build_model(SIZE, len(words)).state_dict(),
                "size": SIZE.model_dump(), "vocabulary": words}, path)
    return path
