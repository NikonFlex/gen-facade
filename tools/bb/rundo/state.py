"""Один `state.json` прогона: атомарная запись под блокировкой и восстановление pending.

Поля — то, что нужно для продолжения: закреплённая база, path worktree, окружение, ID ролей,
стадия, хеши артефактов и одна незавершённая операция (`pending`).
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.bb.rundo.config import Stage

TRANSITIONS = {
    Stage.WORKTREE: {Stage.PLAN},
    Stage.PLAN: {Stage.GEMINI, Stage.RED},
    Stage.GEMINI: {Stage.RED},
    Stage.RED: {Stage.GREEN},
    Stage.GREEN: {Stage.ACCEPTANCE},
    Stage.ACCEPTANCE: {Stage.DRAFT},
    Stage.DRAFT: {Stage.DONE},
}


@dataclass
class State:
    number: str
    project: str
    parent: str
    token: str
    base: str | None = None
    worktree: str | None = None
    stage: Stage = Stage.WORKTREE
    host: str | None = None
    environment_id: str | None = None
    roles: dict[str, str] = field(default_factory=dict)
    pending: dict[str, Any] | None = None
    plan_sha256: str | None = None
    plan_tree: str | None = None
    gate: dict[str, Any] | None = None
    red_tree: str | None = None
    checks_revision: str | None = None
    accepted_revision: str | None = None
    receipts: dict[str, str] = field(default_factory=dict)
    error: str | None = None

    def advance(self, target: Stage) -> None:
        if target not in TRANSITIONS.get(self.stage, ()):
            raise ValueError(f"недопустимый переход {self.stage} → {target}")
        self.stage = target
        self.error = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "project": self.project,
            "parentId": self.parent,
            "token": self.token,
            "base": self.base,
            "worktree": self.worktree,
            "stage": self.stage,
            "host": self.host,
            "environmentId": self.environment_id,
            "roles": self.roles,
            "pending": self.pending,
            "planSha256": self.plan_sha256,
            "planTree": self.plan_tree,
            "gate": self.gate,
            "redTree": self.red_tree,
            "checksRevision": self.checks_revision,
            "acceptedRevision": self.accepted_revision,
            "receipts": self.receipts,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> State:
        return cls(
            number=str(data["number"]),
            project=str(data["project"]),
            parent=str(data["parentId"]),
            token=str(data["token"]),
            base=data.get("base"),
            worktree=data.get("worktree"),
            stage=Stage(data.get("stage", Stage.WORKTREE)),
            host=data.get("host"),
            environment_id=data.get("environmentId"),
            roles=dict(data.get("roles") or {}),
            pending=data.get("pending"),
            plan_sha256=data.get("planSha256"),
            plan_tree=data.get("planTree"),
            gate=data.get("gate"),
            red_tree=data.get("redTree"),
            checks_revision=data.get("checksRevision"),
            accepted_revision=data.get("acceptedRevision"),
            receipts=dict(data.get("receipts") or {}),
            error=data.get("error"),
        )


class StateStore:
    """Каталог прогона в дереве контроллера: state.json, state.lock, журнал команд."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "state.json"
        self.lock_path = directory / "state.lock"

    def load(self) -> State | None:
        if not self.path.is_file():
            return None
        return State.from_dict(json.loads(self.path.read_text(encoding="utf-8")))

    def save(self, state: State) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @contextmanager
    def locked(self):
        """Один прогон на каталог: параллельный запуск ждёт, затем видит готовое состояние."""
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
