#!/bin/sh
# Все проверки проекта одним списком. Запускают CI и хук перед `git commit`
# (.claude/settings.json) — список живёт в одном месте.
# Код 0 — всё прошло, 1 — что-то упало; у упавших печатается хвост вывода.
cd "$(dirname "$0")/.." || exit 1
failed=0

run() {
    name=$1
    shift
    if out=$("$@" 2>&1); then
        echo "ok    $name"
    else
        echo "FAIL  $name"
        printf '%s\n' "$out" | tail -n 30 | sed 's/^/      /'
        failed=1
    fi
}

# Код 5 у pytest — «тестов не найдено»: пока их нет, это не ошибка.
pytest_or_none() {
    python3 -m pytest -q
    code=$?
    [ "$code" -eq 0 ] || [ "$code" -eq 5 ]
}

run "ruff" ruff check .
run "pytest" pytest_or_none
run "backlog.py --selftest" python3 tools/backlog.py --selftest
run "spec_check.py --selftest" python3 tools/spec_check.py --selftest
run "claude_hooks.py --selftest" python3 tools/claude_hooks.py --selftest
run "fpsr.py --selftest" python3 tools/fpsr.py --selftest
run "spec_audit.py --selftest" python3 tools/spec_audit.py --selftest
run "context_check.py --selftest" python3 tools/context_check.py --selftest
run "tg_inbox.py --selftest" python3 tools/tg_inbox.py --selftest
run "tg_export.py --selftest" python3 tools/tg_export.py --selftest
run "tg_notify.py --selftest" python3 tools/tg_notify.py --selftest
run "tg_ping.py --selftest" python3 tools/tg_ping.py --selftest
run "spec_check.py" python3 tools/spec_check.py
run "context_check.py" python3 tools/context_check.py
# data/ и materials/ — гигабайты чужих файлов вне git, поэтому только наши папки
run "jscpd" npx -y jscpd@5.3.3 -c .jscpd.json genfacade tests tools
exit $failed
