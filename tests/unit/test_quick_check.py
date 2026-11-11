"""Быстрая проверка перед коммитом без долгих тестов (gf#165): `check.sh --quick` берёт
`-m "not slow"`, а модуль, который учит модель, гонит Inception или оценку на torch, помечен
`slow`. Полный прогон (`check.sh`, CI) гоняет всё."""

import os
import subprocess
from pathlib import Path

import pytest
from slow_report import Timings

ROOT = Path(__file__).parents[2]
# Признаки долгого модуля: обучение, оценка модели, признаки Inception, torch напрямую.
HEAVY = ("import torch", "fit.run(", "evaluate.run(", "visual.features(")
MARK = "pytestmark = pytest.mark.slow"


def test_quick_check_skips_slow_tests():
    """Без --testmon-forceselect testmon при `-m` гоняет все быстрые тесты (gf#293); хук выбирает
    по базе без трассировки, базу обновляет фон после коммита (gf#443)."""
    quick = '--testmon-nocollect --testmon-forceselect -m "not slow"'
    assert quick in (ROOT / "tools" / "check.sh").read_text()
    assert '--testmon --testmon-forceselect' in SCOPE.read_text()


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


def test_docs_only_of_a_commit_reads_its_files(clone):
    """post-commit спрашивает о сделанном коммите (gf#443): одни .md — базу testmon не обновлять."""
    _, wt = clone
    commit = ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m"]
    (wt / "b.md").write_text("b\n")
    _git(wt, "add", "b.md")
    _git(wt, *commit, "b")
    assert _sh(wt, "docs_only HEAD") == 0
    (wt / "c.py").write_text("x = 1\n")
    _git(wt, "add", "c.py")
    _git(wt, *commit, "c")
    assert _sh(wt, "docs_only HEAD") != 0


def test_docs_only_with_cyrillic_name(clone):
    """git берёт в кавычки имя с не-ASCII буквами («Таблица.md» → "...md\"") —
    всё равно документ."""
    _, wt = clone
    (wt / "Таблица требований.md").write_text("b\n")
    _git(wt, "add", ".")
    assert _sh(wt, "docs_only") == 0


def test_docs_only_commit_skips_hook_queue(clone, tmp_path):
    """Хук перед коммитом: одни .md — без очереди hook_lock (её держит чужой прогон)."""
    _, wt = clone
    (wt / "c.md").write_text("c\n")
    _git(wt, "add", "c.md")
    hook = (ROOT / "templates" / "githooks" / "pre-commit").read_text()
    branch = hook[hook.index("if docs_only"):hook.index("hook_lock.sh\" sh")]
    assert "exit" in branch and _sh(wt, "docs_only") == 0


def test_quick_and_pr_checks_run_on_every_core():
    """Новая функция в общем модуле выбирает больше половины тестов — в один поток 15+ минут
    (gf#443): хук и проверка PR идут процессом на ядро."""
    check = (ROOT / "tools" / "check.sh").read_text()
    assert '-n auto --dist loadfile --testmon-nocollect' in check
    assert 'pytest -q -n auto -m "not slow"' in check


def test_long_unmarked_test_is_named_with_its_setup():
    """Время теста — подготовка и вызов: тяжёлая фикстура ложится на первый тест; помеченный slow
    и уборка не в счёт."""
    t = Timings()
    t.add("a", "setup", 8.0, {})
    t.add("a", "call", 3.0, {})
    t.add("b", "call", 12.0, {"slow": 1})
    t.add("c", "teardown", 30.0, {})
    t.add("d", "call", 4.0, {})
    assert t.unmarked_over(10.0) == [("a", 11.0)]


def test_refresh_after_commit_runs_testmon_in_background_without_git_env(clone, tmp_path):
    """Фон после коммита (gf#443): pytest с трассировкой testmon, без переменных GIT_* хука, один
    на дерево; post-commit его зовёт."""
    _, wt = clone
    seen = tmp_path / "seen"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "python3"
    fake.write_text(f'#!/bin/sh\n{{ env | grep ^GIT_; echo "$@"; }} > {seen}\n')
    fake.chmod(0o755)
    env = {**CLEAN_ENV, "PATH": f"{bin_dir}:{os.environ['PATH']}", "GIT_INDEX_FILE": "x"}
    code = subprocess.run(["sh", "-c", f". {SCOPE}; refresh_testmon_later; wait"],  # noqa: S603, S607
                          cwd=wt, env=env).returncode
    assert code == 0
    text = seen.read_text()
    assert "GIT_" not in text and "--testmon --testmon-forceselect" in text
    hook = (ROOT / "templates" / "githooks" / "post-commit")
    assert "refresh_testmon_later" in hook.read_text() and os.access(hook, os.X_OK)
