"""Очередь хуков (tools/hook_lock.sh): два параллельных вызова идут по очереди, не вместе."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "tools/hook_lock.sh"
pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="нет flock")


def serialized(tmp: Path, wrapper: Path) -> bool:
    """Два вызова пишут «s»/«e» в журнал; по очереди — журнал s e s e, вместе — s s e e."""
    log = tmp / "log"
    job = f"echo s >> {log}; sleep 1; echo e >> {log}"
    env = {"HOOK_LOCK_FILE": str(tmp / "hook.lock"), "PATH": "/usr/bin:/bin"}
    procs = [subprocess.Popen(["sh", str(wrapper), "sh", "-c", job], env=env,  # noqa: S603, S607
                              stderr=subprocess.PIPE, text=True) for _ in range(2)]
    errs = [p.communicate()[1] for p in procs]
    if wrapper == WRAPPER:
        assert any("жду очередь хуков" in e for e in errs)
    return log.read_text().split() == ["s", "e", "s", "e"]


def test_two_hooks_run_in_turn(tmp_path):
    assert serialized(tmp_path, WRAPPER)


def test_without_lock_they_overlap(tmp_path):
    """Красное: обёртка без замка пускает оба сразу — проверка выше это и ловит."""
    broken = tmp_path / "broken.sh"
    broken.write_text('#!/bin/sh\n"$@"\n')
    assert not serialized(tmp_path, broken)
