"""Быстрая проверка перед коммитом без долгих тестов (gf#165): `check.sh --quick` берёт
`-m "not slow"`, а модуль, который учит модель, гонит Inception или оценку на torch, помечен
`slow`. Полный прогон (`check.sh`, CI) гоняет всё."""

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
# Признаки долгого модуля: обучение, оценка модели, признаки Inception, torch напрямую.
HEAVY = ("import torch", "fit.run(", "evaluate.run(", "visual.features(")
MARK = "pytestmark = pytest.mark.slow"


def test_quick_check_skips_slow_tests():
    assert '--testmon -m "not slow"' in (ROOT / "tools" / "check.sh").read_text()


@pytest.mark.parametrize("path", sorted((ROOT / "tests").rglob("test_*.py")), ids=lambda p: p.name)
def test_heavy_module_is_marked_slow(path):
    text = path.read_text()
    if path.name != Path(__file__).name and any(h in text for h in HEAVY):
        assert MARK in text, f"{path.name}: torch или обучение — нужна метка slow"
