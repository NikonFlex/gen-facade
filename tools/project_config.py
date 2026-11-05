"""Настройки проекта, которые читают несколько скриптов: префикс и папка задач, задача клона."""

from __future__ import annotations

import json
import re
from pathlib import Path


def backlog_config(root: Path) -> dict:
    """Префикс и папка задач — из .backlog.json, как у tools/backlog.py."""
    config = root / ".backlog.json"
    cfg = json.loads(config.read_text(encoding="utf-8")) if config.exists() else {}
    return {"prefix": cfg.get("prefix"), "tasks": root / cfg.get("tasks_dir", "docs/tasks")}


def git_dir(root: Path) -> Path:
    """Git-каталог клона; в worktree `.git` — файл со ссылкой на настоящий каталог."""
    git = root / ".git"
    if git.is_file():
        # путь в файле обычно абсолютный; относительный (submodule) считается от корня клона
        git = root / git.read_text(encoding="utf-8").split(":", 1)[1].strip()
    return git


def ticket_file(root: Path) -> Path:
    """Файл, где `git ticket` хранит задачу клона: единственное место, где он назван."""
    return git_dir(root) / "ticket"


def ticket_number(root: Path) -> int | None:
    """Задача клона из `git ticket` (tools/commit_check.py) или None."""
    ticket = ticket_file(root)
    return int(ticket.read_text().strip().split("#")[-1]) if ticket.exists() else None


def branch_number(name: str) -> int | None:
    """Номер задачи из имени ветки: `12-parser`, `agent/12-parser` → 12. Ветки называют
    `<номер>-<имя>` (docs/agents/tasks.md); читает и клон, и PR на GitHub — одним правилом."""
    m = re.search(r"(?:^|/)(\d+)-", name)
    return int(m[1]) if m else None
