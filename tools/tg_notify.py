#!/usr/bin/env python3
"""Событие GitHub → текст уведомления для темы «Задачи и PR» (gf#84).

    python3 tools/tg_notify.py --event ИМЯ --payload СОБЫТИЕ.json [--comments КОММЕНТАРИИ.json]
    python3 tools/tg_notify.py --selftest

Печатает текст в stdout; молчать (черновик PR, зелёный CI, PR закрыт без слияния) — пустой
вывод. Отправляет `tools/tg_inbox.py send --topic tasks`: повторы, деление длинного текста и
выход без токена — там, одним кодом на всех (workflow `tg-notify.yml`).

У закрытой задачи в текст идёт последний комментарий «## Что установлено» — его пишет
`backlog.py comment` перед закрытием (CLAUDE.md, «Задачи»); комментарии workflow берёт
через `gh api` и передаёт файлом.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from project_config import backlog_config
from script_common import report, run_script

SUMMARY = "## Что установлено"
CHECK_WORKFLOW = "check"  # имя workflow из .github/workflows/check.yml


def issue_text(payload: dict, comments: list[dict], prefix: str) -> str:
    issue = payload["issue"]
    name = f"{prefix}#{issue['number']} {issue['title']}"
    if payload["action"] == "opened":
        return f"📌 Новая задача {name}\n{issue['html_url']}"
    if issue.get("state_reason") == "not_planned":
        return f"⏹ Закрыта без выполнения {name}\n{issue['html_url']}"
    summaries = [c["body"] for c in comments if c["body"].startswith(SUMMARY)]
    summary = "\n\n" + summaries[-1].removeprefix(SUMMARY).strip() if summaries else ""
    return f"✅ Закрыта {name}\n{issue['html_url']}{summary}"


def pull_text(payload: dict) -> str:
    pull = payload["pull_request"]
    name = f"PR #{pull['number']} {pull['title']}"
    if payload["action"] == "closed":
        return f"🔀 Слит {name}\n{pull['html_url']}" if pull["merged"] else ""
    if pull["draft"]:
        return ""
    return f"👀 {name} ({pull['head']['ref']} → {pull['base']['ref']})\n{pull['html_url']}"


def run_text(payload: dict) -> str:
    run = payload["workflow_run"]
    if run["name"] != CHECK_WORKFLOW or run["conclusion"] != "failure":
        return ""
    title = run["head_commit"]["message"].splitlines()[0]
    return f"🔴 CI красный на {run['head_branch']}: {title}\n{run['html_url']}"


def text(event: str, payload: dict, comments: list[dict], prefix: str) -> str:
    if event == "issues":
        return issue_text(payload, comments, prefix)
    if event == "pull_request":
        return pull_text(payload)
    if event == "workflow_run":
        return run_text(payload)
    return ""


def run(root: Path) -> int:
    cli = argparse.ArgumentParser(description="событие GitHub → текст для Telegram (gf#84)")
    cli.add_argument("--event", required=True)
    cli.add_argument("--payload", type=Path, required=True)
    cli.add_argument("--comments", type=Path)
    args = cli.parse_args(sys.argv[1:])
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    comments = json.loads(args.comments.read_text(encoding="utf-8")) if args.comments else []
    print(text(args.event, payload, comments, backlog_config(root)["prefix"]), end="")
    return 0


# ---------------------------------------------------------------------------
# selftest: каждое событие — свой текст, молчание там, где шуметь не надо
# ---------------------------------------------------------------------------

URL = "https://github.com/o/r/"
ISSUE = {"number": 7, "title": "Сборщик", "html_url": URL + "issues/7", "state_reason": None}
PULL = {"number": 9, "title": "Сборщик", "html_url": URL + "pull/9", "draft": False,
        "merged": False, "head": {"ref": "7-tg"}, "base": {"ref": "main"}}
RUN = {"name": CHECK_WORKFLOW, "conclusion": "failure", "head_branch": "main",
       "html_url": URL + "actions/runs/1", "head_commit": {"message": "gf#7: сборщик\n\nтело"}}
COMMENTS = [{"body": "## Что установлено\n\n- старое"}, {"body": "просто комментарий"},
            {"body": "## Что установлено\n\n- буфер работает"}]

CASES = [
    ("issues", {"action": "opened", "issue": ISSUE}, [],
     "📌 Новая задача gf#7 Сборщик\n" + URL + "issues/7"),
    ("issues", {"action": "closed", "issue": ISSUE}, COMMENTS,
     "✅ Закрыта gf#7 Сборщик\n" + URL + "issues/7\n\n- буфер работает"),
    ("issues", {"action": "closed", "issue": ISSUE}, [],
     "✅ Закрыта gf#7 Сборщик\n" + URL + "issues/7"),
    ("issues", {"action": "closed", "issue": ISSUE | {"state_reason": "not_planned"}}, COMMENTS,
     "⏹ Закрыта без выполнения gf#7 Сборщик\n" + URL + "issues/7"),
    ("pull_request", {"action": "opened", "pull_request": PULL}, [],
     "👀 PR #9 Сборщик (7-tg → main)\n" + URL + "pull/9"),
    ("pull_request", {"action": "opened", "pull_request": PULL | {"draft": True}}, [], ""),
    ("pull_request", {"action": "closed", "pull_request": PULL | {"merged": True}}, [],
     "🔀 Слит PR #9 Сборщик\n" + URL + "pull/9"),
    ("pull_request", {"action": "closed", "pull_request": PULL}, [], ""),
    ("workflow_run", {"workflow_run": RUN}, [],
     "🔴 CI красный на main: gf#7: сборщик\n" + URL + "actions/runs/1"),
    ("workflow_run", {"workflow_run": RUN | {"conclusion": "success"}}, [], ""),
    ("workflow_run", {"workflow_run": RUN | {"name": "tg-pull"}}, [], ""),
]


def selftest() -> int:
    bad = []
    for number, (event, payload, comments, expected) in enumerate(CASES, 1):
        got = text(event, payload, comments, "gf")
        if got != expected:
            bad.append(f"случай {number} ({event} {payload.get('action', '')}): {got!r}, "
                       f"ждали {expected!r}")
    return report(bad, f"{len(CASES)} событий: задача заведена и закрыта (с итогом, без, "
                       "без выполнения), PR открыт, черновик, слит, закрыт; CI красный и нет")


if __name__ == "__main__":
    sys.exit(run_script(selftest, run))
