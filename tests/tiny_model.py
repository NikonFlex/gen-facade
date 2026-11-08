"""Крошечная необученная модель шага 4 со словарём нынешней записи токенов — для тестов модели
(test_sampling, test_evaluate). Импортируется только там, где torch есть (conftest.py)."""

from pathlib import Path

import torch

from genfacade.config import Config, GPTSize
from genfacade.train import sampling, tokens

SEED = 0
# Окно — с запасом на ответ необученной модели: со словарём gf#321 (`<gable>`, виды окна)
# веса другие, и ответ пачки на простой дом при 704 обрывался на зонах последней стены.
SIZE = GPTSize(block=1024, layers=1, heads=2, width=8, dropout=0.0)


def save(path: Path, cfg: Config) -> Path:
    words = tokens.vocabulary(cfg)
    torch.manual_seed(SEED)  # веса не зависят от того, что тест сэмплировал до сохранения
    torch.save({"model": sampling.build_model(SIZE, len(words)).state_dict(),
                "size": SIZE.model_dump(), "vocabulary": words}, path)
    return path
