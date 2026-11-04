#!/usr/bin/env python3
"""Итог полного набора тестов после мержа → задачи из `Closes` влитых PR (gf#283).

    python3 tools/post_merge.py prev      в stdout `run_id=` и `sha=` прошлого прогона
    python3 tools/post_merge.py verdict --junit F --prev-failed F --out-failed F \
        --base SHA --head SHA

Диапазон — коммиты от прошлого прогона, оставившего список упавших тестов (артефакт
`failed-tests`), до этого. Новый красный (тест падает сейчас и проходил тогда) переоткрывает
задачи диапазона с перечнем тестов; старый красный только комментируется — его задачи переоткрыл
прошлый прогон. Нет отчёта тестов — задачи не трогаются, код 2. Окружение: GITHUB_REPOSITORY,
GITHUB_TOKEN, GITHUB_RUN_ID, RUN_URL.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pr_link import closes  # noqa: E402 — tools/ добавлен в путь строкой выше

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
WORKFLOW = "post-merge.yml"
ARTIFACT = "failed-tests"
MAX_LISTED = 30


def repo() -> str:
    return os.environ["GITHUB_REPOSITORY"]


def api(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(  # noqa: S310 — адрес — API GitHub из окружения прогона
        f"{API}{path}", method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                 "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
        raw = r.read()
    return json.loads(raw) if raw else None


def prev() -> int:
    """Прошлый завершённый прогон на main, у которого остался список упавших."""
    me = int(os.environ["GITHUB_RUN_ID"])
    runs = api("GET", f"/repos/{repo()}/actions/workflows/{WORKFLOW}/runs"
                      "?branch=main&status=completed&per_page=30")["workflow_runs"]
    for run in runs:
        if run["id"] == me:
            continue
        arts = api("GET", f"/repos/{repo()}/actions/runs/{run['id']}/artifacts")["artifacts"]
        if any(a["name"] == ARTIFACT and not a["expired"] for a in arts):
            print(f"run_id={run['id']}\nsha={run['head_sha']}")
            return 0
    print("run_id=\nsha=")
    return 0


def failed_tests(path: Path) -> set[str] | None:
    """Упавшие тесты отчёта JUnit; отчёта нет — None."""
    if not path.is_file():
        return None
    return {f"{c.get('classname', '')}::{c.get('name')}"
            # отчёт пишет наш же pytest в этом прогоне — не чужие данные
            for c in ElementTree.parse(path).iter("testcase")  # noqa: S314
            if c.find("failure") is not None or c.find("error") is not None}


def merged_tasks(base: str, head: str) -> dict[str, set[int]]:
    """Задачи из `Closes` PR, влитых между base и head: `owner/repo#N` → номера PR."""
    if base:
        shas = [c["sha"] for c in api("GET", f"/repos/{repo()}/compare/{base}...{head}")["commits"]]
    else:
        shas = [head]
    tasks: dict[str, set[int]] = {}
    for sha in shas:
        for pr in api("GET", f"/repos/{repo()}/commits/{sha}/pulls"):
            if pr.get("merged_at") and pr["base"]["ref"] == "main":
                for ref in closes(pr.get("body") or "", repo()):
                    tasks.setdefault(ref, set()).add(pr["number"])
    return tasks


def comment(new_red: list[str], now: set[str], prs: str, run_url: str) -> str:
    if new_red:
        listed = "\n".join(f"- `{t}`" for t in new_red[:MAX_LISTED])
        more = f"\n- … и ещё {len(new_red) - MAX_LISTED}" if len(new_red) > MAX_LISTED else ""
        return (f"Переоткрыта: после мержа {prs} полный набор упал на тестах, которые в прошлом "
                f"прогоне проходили. Прогон: {run_url}\n\n{listed}{more}")
    if now:
        return (f"Полный набор после мержа {prs}: `main` красный, но эти тесты падали и до него — "
                f"задача не переоткрыта. Прогон: {run_url}")
    return f"Полный набор после мержа {prs} зелёный. Прогон: {run_url}"


def verdict(a: argparse.Namespace) -> int:
    now = failed_tests(Path(a.junit))
    if now is None:
        print("::error::отчёта тестов нет — набор не дошёл до конца; задачи не трогаю")
        return 2
    Path(a.out_failed).write_text("".join(f"{t}\n" for t in sorted(now)), encoding="utf-8")
    prev_file = Path(a.prev_failed)
    before = set(prev_file.read_text(encoding="utf-8").splitlines()) if prev_file.is_file() \
        else set()
    new_red = sorted(now - before)
    for ref, prs in sorted(merged_tasks(a.base, a.head).items()):
        where, num = ref.split("#")
        if where != repo():
            print(f"::warning::{ref}: задача другого репозитория, токен прогона её не переоткроет")
            continue
        if new_red:
            api("PATCH", f"/repos/{repo()}/issues/{num}", {"state": "open"})
        text = comment(new_red, now, ", ".join(f"#{n}" for n in sorted(prs)),
                       os.environ["RUN_URL"])
        api("POST", f"/repos/{repo()}/issues/{num}/comments", {"body": text})
        print(f"{ref}: {'переоткрыта' if new_red else 'не переоткрыта'}")
    return 1 if now else 0


def selftest() -> int:
    """Текст комментария по трём исходам и чтение отчёта JUnit — без сети."""
    import tempfile
    bad = []
    if not comment(["a::b"], {"a::b"}, "#1", "u").startswith("Переоткрыта"):
        bad.append("новый красный — не «Переоткрыта»")
    if "падали и до него" not in comment([], {"a::b"}, "#1", "u"):
        bad.append("старый красный — не «падали и до него»")
    if "зелёный" not in comment([], set(), "#1", "u"):
        bad.append("зелёный — не «зелёный»")
    with tempfile.TemporaryDirectory() as d:
        junit = Path(d) / "j.xml"
        junit.write_text('<testsuite><testcase classname="t" name="ok"/><testcase classname="t" '
                         'name="bad"><failure/></testcase></testsuite>', encoding="utf-8")
        if failed_tests(junit) != {"t::bad"} or failed_tests(Path(d) / "нет.xml") is not None:
            bad.append("отчёт JUnit: упавшие или отсутствие отчёта")
    for line in bad:
        print("✗ " + line)
    if not bad:
        print("самопроверка пройдена: комментарий по трём исходам, отчёт JUnit")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prev")
    v = sub.add_parser("verdict")
    v.add_argument("--junit", required=True)
    v.add_argument("--prev-failed", required=True)
    v.add_argument("--out-failed", required=True)
    v.add_argument("--base", default="")
    v.add_argument("--head", required=True)
    args = p.parse_args()
    sys.exit(prev() if args.cmd == "prev" else verdict(args))
