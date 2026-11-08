"""Сторож запуска субагента (gf#358): вход хука Claude Code → код возврата `guard.py claude`.

Проверяем как хук: JSON на stdin, отказ — код 2 и причина в stderr.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / ".agents/guards/guard.py"


def hook(tool_name: str, tool_input: dict) -> subprocess.CompletedProcess:
    event = {"tool_name": tool_name, "tool_input": tool_input}
    return subprocess.run([sys.executable, str(GUARD), "claude"], input=json.dumps(event),  # noqa: S603
                          capture_output=True, text=True, check=False, cwd=ROOT)


def agent(model: str | None, prompt: str) -> subprocess.CompletedProcess:
    return hook("Agent", {"prompt": prompt, "description": "x", "subagent_type": "claude",
                          **({"model": model} if model else {})})


@pytest.mark.parametrize(("model", "prompt"), [
    ("opus", "Сделай дизайн смотрелки"),
    ("opus", "Opus: дизайн\nсделай"),
    (None, "Opus: формат токенов"),
])
def test_denied(model, prompt):
    done = agent(model, prompt)
    assert done.returncode == 2
    assert "haiku" in done.stderr
    assert "sonnet" in done.stderr
    assert "Opus:" in done.stderr


@pytest.mark.parametrize(("model", "prompt"), [
    ("opus", "Opus: формат токенов\nсделай"),
    ("opus", "\nOpus: страж"),
    ("opus", "Opus: архитектура модели"),
    ("sonnet", "код"),
    ("haiku", "прогон"),
])
def test_allowed(model, prompt):
    assert agent(model, prompt).returncode == 0


def test_other_tool_unchanged():
    assert hook("Bash", {"command": "git log --oneline"}).returncode == 0
    assert hook("Bash", {"command": "cat .env"}).returncode == 2
