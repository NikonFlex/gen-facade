"""Самопроверка сторожей (`python3 .agents/guards/guard.py --selftest`): без сети.

Каждый сторож отказывает или спрашивает на своём запрещённом входе и молчит на соседнем
безобидном; входы сред дают свой формат; правила Codex совпадают со списком ASK.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from guard import (
    CODEX_RULES,
    ROOT,
    Call,
    Verdict,
    codex_rules,
    decide,
    to_claude,
    to_codex,
    to_cursor,
)
from script_common import git_env, report, write_files

#: (вызов, ожидаемый ответ, кусок причины) — по запрещённому и безобидному входу на сторож.
CASES = [
    (Call(command="git push origin main"), Verdict.ASK, "запись в GitHub"),
    (Call(command="cd repo && gh pr merge 12"), Verdict.ASK, "gh pr merge"),
    (Call(command="gh issue view 12"), Verdict.ALLOW, ""),
    (Call(command="git log --oneline"), Verdict.ALLOW, ""),
    (Call(command="ssh deploy@prod-1 systemctl restart app"), Verdict.ASK, "прод"),
    (Call(command="cat .env"), Verdict.DENY, "ключами"),
    (Call(path="/repo/.env.local"), Verdict.DENY, "ключами"),
    (Call(command="cat .env.example"), Verdict.ALLOW, ""),
    (Call(command="git commit -m 'Closes #12'"), Verdict.DENY, "Closes #12"),
    (Call(command="git commit -m 'Implements ab#12'"), Verdict.ALLOW, ""),
    (Call(command="gh pr create --title t --body 'Fixes #12'"), Verdict.DENY, "Closes #N"),
    (Call(command="gh pr create --title t --body 'Задача ab#12'"), Verdict.DENY, "Closes #N"),
    (Call(command="gh pr create --title 'Fix #12 x' --body 'Closes #12'"), Verdict.DENY,
     "заголовке"),
    # GitHub закрывает задачу и по адресу, и по gf#N — как по `#N`
    (Call(command="gh pr create --title t --body 'Closes #12\nfixes https://github.com/a/b/issues/5'"),
     Verdict.DENY, "по этому слову"),
    (Call(command="gh pr create --fill"), Verdict.DENY, "--body-file"),
    # `;` вплотную к слову: до gf#293 тело PR такой команды сторож не проверял
    (Call(command="gh pr create;ls"), Verdict.DENY, "--body"),
    (Call(command="echo ok;gh pr create --fill"), Verdict.DENY, "--body-file"),
    (Call(command="cat x.pem"), Verdict.DENY, "ключами"),
    (Call(command="git commit --no-verify -m x"), Verdict.DENY, "хуки git"),
    (Call(command="git -c core.hooksPath=/dev/null commit -m x"), Verdict.DENY, "хуки git"),
    (Call(command="git log --no-verify-x"), Verdict.ALLOW, ""),
    (Call(command="git commit -q -F - <<'EOF'\nci: x\n\nСторож отбивает gh pr create\nEOF"),
     Verdict.ALLOW, ""),
]


def agent(model: str | None, prompt: str) -> Call:
    return Call(agent={"prompt": prompt, "description": "x", **({"model": model} if model else {})})


#: Запуск субагента (gf#358): (вызов, ответ, кусок причины).
AGENT_CASES = [
    (agent("opus", "Сделай дизайн смотрелки"), Verdict.DENY, "без причины"),
    (agent("opus", ""), Verdict.DENY, "без причины"),
    (agent("opus", "Opus: дизайн\nсделай"), Verdict.DENY, "без причины"),
    (agent("opus", "\n\nOpus: формат токенов\nсделай"), Verdict.ALLOW, ""),
    (agent("opus", "Opus: Страж"), Verdict.ALLOW, ""),
    (agent(None, "Opus: страж"), Verdict.DENY, "нет `model`"),
    (agent("sonnet", "код"), Verdict.ALLOW, ""),
    (agent("haiku", "прогон"), Verdict.ALLOW, ""),
    (agent("fable", "x"), Verdict.DENY, "кому что отдавать"),
]


def project(root: Path, repeat: bool, gated: bool) -> Path:
    bottom = "Локальный повтор: не требуется — настройка\n" if repeat else ""
    files = {
        ".backlog.json": '{"prefix": "ab"}',
        ".agents/guards/config.json": json.dumps({
            "prod": [r"\bssh\s+\S*prod"], "secret_files": [r"^\.env(\..+)?$", r"\.pem$"],
            "secret_allow": [".env.example"], "opus_reasons": ["формат токенов", "страж"]}),
        "tools/receipt.json": json.dumps({"exclude": [], "gated": gated}),
        "docs/tasks/ab-0012.md": f"# ab#12\n\n<!-- ↓↓↓ ниже наше: скрипт эту часть не трогает "
                                 f"↓↓↓ -->\n\n{bottom}",
        "app.py": "x = 1\n",
        # похожее имя: по glob `*-0012.md` оно встало бы первым, но это не файл задачи 12
        "docs/tasks/aa-x-0012.md": "# чужой файл без метки и повтора\n",
    }
    write_files(root, files)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=git_env())  # noqa: S607
    (root / ".git/ticket").write_text("ab#12\n")
    return root


def cases(root: Path, table: list = CASES) -> list[str]:
    bad = []
    for call, wanted, reason in table:
        verdict, why = decide(call, root)
        if verdict != wanted or reason not in why:
            bad.append(f"{call}: {verdict} «{why}», ждали {wanted} «{reason}»")
    return bad


def pr_and_push(tmp: Path) -> list[str]:
    bad = []
    pr = Call(command="gh pr create --title x --body 'Closes #12'")
    if decide(pr, project(tmp / "no-repeat", repeat=False, gated=False))[0] != Verdict.DENY:
        bad.append("PR без «Локальный повтор» не остановлен")
    if decide(pr, project(tmp / "repeat", repeat=True, gated=False))[0] != Verdict.ASK:
        bad.append("PR с «Локальный повтор» не дошёл до вопроса человеку")
    push = Call(command="git push")
    root = project(tmp / "gated", repeat=True, gated=True)
    os.environ["STAND_STATE_DIR"] = str(tmp / "state")
    if decide(push, root)[0] != Verdict.DENY:
        bad.append("push без квитанции при включённом гейте не остановлен")
    from scenario import Mode, write_receipt
    write_receipt(root, Mode.REPLAY, passed=True)
    if decide(push, root)[0] != Verdict.DENY:
        bad.append("квитанция replay пропустила push — нужна live или record")
    write_receipt(root, Mode.LIVE, passed=True)
    if decide(push, root)[0] != Verdict.ASK:
        bad.append("квитанция live «прошло» не пропустила push к вопросу человеку")
    (root / "app.py").write_text("x = 2\n")
    if decide(push, root)[0] != Verdict.DENY:
        bad.append("правка кода после квитанции не сбросила её")
    (root / ".agents/guards/config.json").unlink()
    verdict, why = decide(Call(command="git log"), root)
    if verdict != Verdict.DENY or "упал" not in why:
        bad.append("без config.json сторож пропустил команду — ждали отказ «сторож … упал»")
    return bad


def corrupt_receipts(tmp: Path) -> list[str]:
    """Битая строка журнала квитанций не отменяет годную рядом; без годной push остановлен."""
    from scenario import Mode, state_dir, write_receipt
    root = project(tmp / "corrupt", repeat=True, gated=True)
    os.environ["STAND_STATE_DIR"] = str(tmp / "state-corrupt")
    log = state_dir() / "receipts.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("{битая строка\n[]\n", encoding="utf-8")
    push, bad = Call(command="git push"), []
    if decide(push, root)[0] != Verdict.DENY:
        bad.append("журнал из одних битых строк пропустил push")
    write_receipt(root, Mode.LIVE, passed=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("{ещё одна битая\n")
    if decide(push, root)[0] != Verdict.ASK:
        bad.append("битые строки рядом с годной квитанцией остановили push")
    return bad


def formats() -> list[str]:
    bad = []
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = to_claude(Verdict.DENY, "нельзя")
    if code != 2 or "нельзя" not in err.getvalue():
        bad.append("Claude: отказ — не код 2 с причиной в stderr")
    out = io.StringIO()
    with redirect_stdout(out):
        to_claude(Verdict.ASK, "спроси")
    if json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecision"] != "ask":
        bad.append("Claude: вопрос — не permissionDecision ask")
    with redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
        codes = (to_codex(Verdict.DENY, "x"), to_codex(Verdict.ASK, "x"))
    if codes != (2, 0) or out.getvalue():
        bad.append("Codex: отказ — код 2, вопрос — без вывода (его задаёт execpolicy)")
    out = io.StringIO()
    with redirect_stdout(out):
        to_cursor(Verdict.DENY, "нельзя")
    if json.loads(out.getvalue()) != {"permission": "deny", "userMessage": "нельзя",
                                      "agentMessage": "нельзя"}:
        bad.append("Cursor: формат ответа не тот")
    if (ROOT / CODEX_RULES).read_text(encoding="utf-8") != codex_rules():
        bad.append(f"{CODEX_RULES} не совпадает с ASK — guard.py --write-codex-rules")
    return bad


def selftest() -> int:
    state = os.environ.get("STAND_STATE_DIR")
    with tempfile.TemporaryDirectory() as tmp:
        root = project(Path(tmp) / "base", repeat=True, gated=False)
        bad = (cases(root) + cases(root, AGENT_CASES) + pr_and_push(Path(tmp))
               + corrupt_receipts(Path(tmp)) + formats())
    if state is None:
        os.environ.pop("STAND_STATE_DIR", None)
    else:
        os.environ["STAND_STATE_DIR"] = state
    return report(bad, f"{len(CASES)} входов сторожей, {len(AGENT_CASES)} запусков субагента, "
                       "PR без «Локального повтора», квитанция push (и битые строки журнала), "
                       "форматы Claude Code / Codex / Cursor, правила Codex")
