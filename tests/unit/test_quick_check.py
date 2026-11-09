"""Быстрая проверка перед коммитом без долгих тестов (gf#165): `check.sh --quick` берёт
`-m "not slow"`, а модуль, который учит модель, гонит Inception или оценку на torch, помечен
`slow`. Полный прогон (`check.sh`, CI) гоняет всё."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
# Признаки долгого модуля: обучение, оценка модели, признаки Inception, torch напрямую.
HEAVY = ("import torch", "fit.run(", "evaluate.run(", "visual.features(")
MARK = "pytestmark = pytest.mark.slow"


def test_quick_check_skips_slow_tests():
    """Без --testmon-forceselect testmon при `-m` гоняет все быстрые тесты (gf#293)."""
    quick = '--testmon --testmon-forceselect -m "not slow"'
    assert quick in (ROOT / "tools" / "check.sh").read_text()


@pytest.mark.parametrize("path", sorted((ROOT / "tests").rglob("test_*.py")), ids=lambda p: p.name)
def test_heavy_module_is_marked_slow(path):
    text = path.read_text()
    if path.name != Path(__file__).name and any(h in text for h in HEAVY):
        assert MARK in text, f"{path.name}: torch или обучение — нужна метка slow"


SCOPE = ROOT / "tools" / "quick_scope.sh"
# Хук перед коммитом гоняет тесты с GIT_DIR и GIT_INDEX_FILE настоящего репозитория: git в
# папке теста (tmp_path) без чистки окружения пишет в него (09.11: клон стал bare, коммит «a»).
CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def _sh(cwd: Path, script: str) -> int:
    return subprocess.run(["sh", "-c", f". {SCOPE}; {script}"], cwd=cwd, env=CLEAN_ENV).returncode  # noqa: S603, S607


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=CLEAN_ENV)  # noqa: S603, S607


@pytest.fixture
def clone(tmp_path):
    """Клон с коммитом и вторым рабочим деревом без базы testmon (gf#374)."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q")
    (main / "a.md").write_text("a\n")
    _git(main, "add", ".")
    _git(main, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "a")
    _git(main, "worktree", "add", "-q", str(tmp_path / "wt"))
    return main, tmp_path / "wt"


def test_new_worktree_takes_testmon_base(clone):
    main, wt = clone
    (main / ".testmondata").write_bytes(b"base")
    assert _sh(wt, "seed_testmon") == 0
    assert (wt / ".testmondata").read_bytes() == b"base"


def test_own_testmon_base_is_kept(clone):
    main, wt = clone
    (main / ".testmondata").write_bytes(b"base")
    (wt / ".testmondata").write_bytes(b"own")
    _sh(wt, "seed_testmon")
    assert (wt / ".testmondata").read_bytes() == b"own"


def test_docs_only_commit_skips_tests(clone):
    _, wt = clone
    (wt / "b.md").write_text("b\n")
    _git(wt, "add", "b.md")
    assert _sh(wt, "docs_only") == 0
    (wt / "c.py").write_text("x = 1\n")
    _git(wt, "add", "c.py")
    assert _sh(wt, "docs_only") != 0
