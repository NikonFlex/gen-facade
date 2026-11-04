"""Логика страницы смотрелки без браузера: тесты node (`tests/js/*.test.mjs`)."""

import subprocess  # noqa: S404 — только node --test по своим файлам
from pathlib import Path

JS_TESTS = Path(__file__).parents[1] / "js"


def test_page_logic_in_node():
    files = sorted(str(p) for p in JS_TESTS.glob("*.test.mjs"))
    got = subprocess.run(["node", "--test", *files], capture_output=True, text=True)  # noqa: S603, S607
    assert got.returncode == 0, got.stdout + got.stderr
