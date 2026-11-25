"""Git-снимок, фактические прогоны pytest и выдержки для Jev."""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from textwrap import indent
from typing import Any
from xml.etree import ElementTree

from tools.bb.rundo.artifacts import RedNode, evidence_tests, truncate
from tools.bb.rundo.config import (
    CHECK_COMMAND,
    MAX_EVIDENCE,
    normalize_path,
)
from tools.script_common import git_env

PYTEST_TIMEOUT_SECONDS = 1800
QUICK_TIMEOUT_SECONDS = 1800
MIN_FRAGMENT = 200
SKIP_RESERVE_MAX = 4000
BRIEF_LINES = 7
BRIEF_LINE_CHARS = 220
TEST_SOURCE_CHARS = 900


class EvidenceError(RuntimeError):
    pass


class Evidence:
    """Проверки в одном worktree; артефакты пишутся в каталог обмена прогона."""

    def __init__(self, worktree: Path, exchange: Path) -> None:
        self.worktree = worktree
        self.exchange = exchange
        self.python = _python_for(worktree)

    def changed(self) -> set[str]:
        return changed_paths(self.worktree)

    def revision(self, planned: Sequence[str], *, scoped: bool = False) -> str:
        for path in planned:
            if (self.worktree / path).is_file() and not _tracked(self.worktree, path):
                _git_text(self.worktree, "add", "-N", "--", path)
        head = _git_bytes(self.worktree, "rev-parse", "HEAD")
        scope = tuple(planned) if scoped else ()
        diff = b"" if scoped and not scope else _git_bytes(
            self.worktree, "diff", "--binary", "HEAD", "--", *scope,
        )
        return hashlib.sha256(head + diff).hexdigest()

    def diff(self, plan: dict[str, Any]) -> str:
        """Реализации — полными -U0 фрагментами; остаток — test и spec/task с подписями.

        SHA привязан к полному диффу (`revision`), здесь меняется только выдержка для Jev.
        """
        groups = _diff_groups(plan)
        full = self._diff_text(())
        (self.exchange / "diff.patch").write_text(full, encoding="utf-8")
        notes = {
            path: _skip_note(path) for path in (*groups["test"], *groups["other"])
        }
        reserve = min(sum(len(note) for note in notes.values()), SKIP_RESERVE_MAX)
        implementation = self._implementation_diff(
            groups["implementation"], MAX_EVIDENCE - reserve,
        )
        remaining = MAX_EVIDENCE - len(implementation)
        other_reserve = sum(len(notes[path]) for path in groups["other"])
        tests = self._group_diff(groups["test"], remaining, notes, other_reserve)
        remaining -= len(tests)
        rest = self._group_diff(groups["other"], remaining, notes, 0)
        return (implementation + tests + rest)[:MAX_EVIDENCE]

    def run_red(self, node: RedNode, revision: str) -> None:
        code, cases = self._run_test(node, "red", revision)
        if code != 1:
            raise EvidenceError(f"красный прогон завершился с кодом {code}, ожидался 1")
        assert_red(cases, node)

    def run_green(self, node: RedNode, revision: str) -> None:
        code, cases = self._run_test(node, "green", revision)
        if code != 0:
            raise EvidenceError(f"зелёный прогон завершился с кодом {code}, ожидался 0")
        assert_green(cases, node)

    def run_tests(self, paths: Sequence[str], revision: str) -> None:
        """Все объявленные пути test: отдельный прогон после зелёного JUnit."""
        argv = [self.python, "-m", "pytest", "-v", *paths, "-p", "no:cacheprovider"]
        done = run_command(argv, self.worktree, QUICK_TIMEOUT_SECONDS)
        _write_log(self.exchange / "tests.log", argv, self.worktree, revision, done)
        if done.returncode != 0:
            raise EvidenceError(f"pytest по путям test: код {done.returncode}")

    def run_quick(self, revision: str) -> None:
        argv = list(CHECK_COMMAND)
        done = run_command(argv, self.worktree, QUICK_TIMEOUT_SECONDS)
        _write_log(self.exchange / "quick.log", argv, self.worktree, revision, done)
        if done.returncode != 0:
            raise EvidenceError(f"sh tools/check.sh --quick: код {done.returncode}")

    def _run_test(self, node: RedNode, label: str, revision: str) -> tuple[int, list]:
        report = self.exchange / f"{label}.xml"
        argv = [
            self.python, "-m", "pytest", "-v", node.node_id,
            f"--junitxml={report}", "-p", "no:cacheprovider",
        ]
        done = run_command(argv, self.worktree, PYTEST_TIMEOUT_SECONDS)
        _write_log(self.exchange / f"{label}.log", argv, self.worktree, revision, done)
        return done.returncode, parse_junit(report)

    def test_output(self, plan: dict[str, Any]) -> str:
        parts: list[str] = []
        for label in ("red", "green", "quick"):
            parts.append(f"[{label}]")
            parts.extend(self._brief_log(self.exchange / f"{label}.log", label))
        tests = self._test_results()
        selected = evidence_tests(plan)
        for node_id in selected:
            result = tests.get(node_id)
            if result != "PASSED":
                raise EvidenceError(f"tests.log: нет успешной проверки {node_id}: {result}")
            parts.extend((f"{node_id} {result}", _test_source(self.worktree, node_id)))
        parts.append("[tests] остальные результаты")
        prefix = "\n".join(parts)
        other = [f"{node} {outcome}" for node, outcome in tests.items() if node not in selected]
        return truncate("\n".join([prefix, *_fit_lines(other, MAX_EVIDENCE - len(prefix) - 1)]))

    def _diff_text(self, paths: Sequence[str]) -> str:
        return _git_bytes(
            self.worktree, "diff", "--binary", "-U0", "HEAD", "--", *paths,
        ).decode("utf-8", errors="replace")

    def _implementation_diff(self, paths: list[str], budget: int) -> str:
        fragments = [(path, self._diff_text((path,))) for path in paths]
        fragments = [(path, text) for path, text in fragments if text]
        if not fragments:
            return ""
        total = sum(len(text) for _, text in fragments)
        if total <= budget:
            return "".join(text for _, text in fragments)
        share = max(MIN_FRAGMENT, budget // len(fragments))
        parts: list[str] = []
        used = 0
        for path, text in fragments:
            note = _shorten_note(path)
            available = budget - used
            if available <= len(note):
                parts.append(note[:available])
                break
            room = max(0, min(share, available) - len(note))
            part = text[:room] + note
            parts.append(part)
            used += len(part)
        return "".join(parts)

    def _group_diff(self, paths: list[str], budget: int, notes: dict[str, str],
                    future_reserve: int) -> str:
        reserve = sum(len(notes[path]) for path in paths) + future_reserve
        available = max(0, budget - reserve)
        parts: list[str] = []
        used = 0
        for path in paths:
            fragment = self._diff_text((path,))
            if not fragment:
                continue
            if used + len(fragment) <= available:
                parts.append(fragment)
                used += len(fragment)
            elif used + len(notes[path]) <= budget:
                parts.append(notes[path])
                used += len(notes[path])
        return "".join(parts)

    def _brief_log(self, path: Path, label: str) -> list[str]:
        if not path.is_file():
            return ["нет файла"]
        lines: list[str] = []
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line.startswith("exit code:"):
                lines.append(line)
            elif label == "red" and (line.startswith("FAILED ") or "AssertionError" in line):
                lines.append(line)
            elif label == "green" and "PASSED" in line:
                lines.append(line)
            elif label == "quick" and (line.startswith("ok ") or line.startswith("FAIL ")):
                lines.append(line)
        if not lines:
            tail = [line for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
                    if line.strip()][-2:]
            lines = [line.strip() for line in tail]
        return [line[:BRIEF_LINE_CHARS] for line in lines[:BRIEF_LINES]]

    def _test_results(self) -> dict[str, str]:
        path = self.exchange / "tests.log"
        if not path.is_file():
            raise EvidenceError(f"нет прогона по путям test: {path}")
        outcome = re.compile(r"^(?P<node>.+::.+?)\s+(?P<state>PASSED|FAILED|ERROR|SKIPPED)\b")
        results = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if match := outcome.match(line.strip()):
                results[match["node"]] = match["state"]
        return results


def _test_source(worktree: Path, node_id: str) -> str:
    path, *names = node_id.partition("[")[0].split("::")
    source = (worktree / path).read_text(encoding="utf-8")
    node = ast.parse(source, filename=path)
    for name in names:
        node = next((child for child in node.body if getattr(child, "name", None) == name), None)
        if node is None:
            raise EvidenceError(f"не найден исходник проверки {node_id}")
    fragment = ast.get_source_segment(source, node)
    if not fragment:
        raise EvidenceError(f"пустой исходник проверки {node_id}")
    if len(fragment) > TEST_SOURCE_CHARS:
        fragment = fragment[:TEST_SOURCE_CHARS].rstrip() + "\n[исходник сокращён]"
    return indent(fragment, "    ")


def worktree_add(repo: Path, path: Path, base: str) -> None:
    """Чистый worktree от закреплённой базы; единственный git-помощник создания."""
    _git_text(repo, "worktree", "add", "--detach", str(path), base)


def _python_for(worktree: Path) -> str:
    """Python дерева: окружение worktree, иначе тот, что запустил контроллер."""
    candidate = worktree / ".venv" / "bin" / "python3"
    return str(candidate) if candidate.is_file() else sys.executable


def changed_paths(worktree: Path) -> set[str]:
    return _porcelain_paths(
        _git_text(worktree, "status", "--porcelain", "--untracked-files=all", "-z"),
    )


def head(worktree: Path) -> str:
    return _git_text(worktree, "rev-parse", "HEAD").strip()


def parse_junit(path: Path) -> list:
    try:
        root = ElementTree.parse(path).getroot()  # noqa: S314 — отчёт своего прогона pytest
    except (OSError, ElementTree.ParseError) as error:
        raise EvidenceError(f"{path}: JUnit не разобран ({error})") from error
    return list(root.findall(".//testcase"))


def assert_red(cases: list, node: RedNode) -> None:
    case = _single_case(cases, node)
    failure = case.find("failure")
    if failure is None:
        raise EvidenceError("красный JUnit: testcase без failure")
    text = (failure.get("message") or "") + (failure.text or "")
    if node.marker not in text:
        raise EvidenceError(f"красный JUnit: в failure нет маркера {node.marker!r}")


def assert_green(cases: list, node: RedNode) -> None:
    case = _single_case(cases, node)
    if case.find("failure") is not None:
        raise EvidenceError("зелёный JUnit: testcase с failure")


def _single_case(cases: list, node: RedNode) -> Any:
    name = node.node_id.rsplit("::", 1)[-1]
    if len(cases) != 1:
        raise EvidenceError(f"JUnit: ожидался один testcase, их {len(cases)}")
    case = cases[0]
    if not str(case.get("name", "")).endswith(name):
        raise EvidenceError(f"JUnit: чужой testcase {case.get('name')!r}")
    if case.find("error") is not None or case.find("skipped") is not None:
        raise EvidenceError("JUnit: error или skipped вместо ожидаемого исхода")
    return case


def _porcelain_paths(text: str) -> set[str]:
    paths: set[str] = set()
    skip_next = False
    for entry in text.split("\0"):
        if skip_next:
            skip_next = False
            continue
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        paths.add(path)
        skip_next = "R" in status or "C" in status
    return paths


def _tracked(worktree: Path, relative: str) -> bool:
    done = subprocess.run(  # noqa: S603, S607
        ["git", "--literal-pathspecs", "-C", str(worktree), "ls-files",  # noqa: S607
         "--error-unmatch", "--", relative],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        env=git_env(),
    )
    return done.returncode == 0


def _git_text(worktree: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603, S607
        ["git", "--literal-pathspecs", "-C", str(worktree), *args], capture_output=True, text=True,  # noqa: S607
        encoding="utf-8", errors="replace", check=False, env=git_env(),
    )
    if done.returncode != 0:
        raise EvidenceError(f"git {args[0]}: {done.stderr.strip()}")
    return done.stdout


def _git_bytes(worktree: Path, *args: str) -> bytes:
    done = subprocess.run(  # noqa: S603, S607
        ["git", "--literal-pathspecs", "-C", str(worktree), *args],  # noqa: S607
        capture_output=True, check=False,
        env=git_env(),
    )
    if done.returncode != 0:
        raise EvidenceError(f"git {args[0]}: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def run_command(argv: Sequence[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    env = git_env()
    bin_dir = cwd / ".venv" / "bin"
    if bin_dir.is_dir():
        env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", os.defpath)
    return subprocess.run(  # noqa: S603 — argv собран контроллером, не моделью
        list(argv), cwd=cwd, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace", env=env, check=False,
    )


def _write_log(path: Path, argv: Sequence[str], cwd: Path, revision: str,
               done: subprocess.CompletedProcess[str]) -> None:
    header = [
        "command: " + " ".join(argv),
        f"cwd: {cwd}",
        f"tree: {revision}",
        f"exit code: {done.returncode}",
        "---",
    ]
    path.write_text("\n".join([*header, done.stdout, done.stderr]), encoding="utf-8")


def _diff_groups(plan: dict[str, Any]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {"implementation": [], "test": [], "other": []}
    for item in plan["paths"]:
        purpose = item["purpose"]
        key = "implementation" if purpose == "implementation" else (
            "test" if purpose == "test" else "other"
        )
        path = normalize_path(item["path"])
        if path not in groups[key]:
            groups[key].append(path)
    return groups


def _skip_note(path: str) -> str:
    return f"[пропуск {path}: не вошёл в лимит Jev; полный -U0 diff в diff.patch]\n"


def _shorten_note(path: str) -> str:
    return f"[сокращено {path}: полный -U0 diff в diff.patch]\n"


def _fit_lines(lines: list[str], budget: int) -> list[str]:
    included: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > budget:
            included.append(f"... ещё {len(lines) - len(included)}")
            break
        included.append(line)
        used += len(line) + 1
    return included
