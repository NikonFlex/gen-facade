# Что гонять в хуке перед коммитом (`check.sh --quick`, gf#374). Подключается через `.`.
#
# База testmon (.testmondata) — своя у каждого рабочего дерева: новое дерево без неё гоняет все
# быстрые тесты (~10 мин; 09.11 шесть новых деревьев агентов дали очередь хуков почти на час).
# seed_testmon берёт самую свежую базу среди деревьев клона: testmon сам перегонит тесты, чей код
# с тех пор поменялся, — отбор остаётся верным (замер 09.11: копия базы — 15 с вместо 10 мин).
seed_testmon() {
    [ -e .testmondata ] && return 0
    newest=$(git worktree list --porcelain | sed -n 's/^worktree //p' | while read -r dir; do
        [ -f "$dir/.testmondata" ] && echo "$dir/.testmondata"
    done | xargs -r ls -t 2>/dev/null | head -n 1)
    [ -n "$newest" ] && cp "$newest" .testmondata
    return 0
}

# Коммит, где все файлы — .md: тестам нечего проверять, pytest не гоняется (ruff, gitleaks и
# проверки задач остаются; полный набор — в CI).
# С ревизией — файлы этого коммита (post-commit), без — индекс (pre-commit).
docs_only() {
    if [ -n "${1:-}" ]; then
        files=$(git -c core.quotePath=false diff-tree --no-commit-id --name-only -r "$1")
    else
        files=$(git -c core.quotePath=false diff --cached --name-only)
    fi
    [ -n "$files" ] && ! printf '%s\n' "$files" | grep -qv '\.md$'
}

# После коммита (templates/githooks/post-commit, gf#443): база testmon заново по тем тестам, что
# выбрал бы хук, — с трассировкой, в фоне, с низким приоритетом; git не ждёт. Один прогон на
# дерево (замок рядом с .git дерева), вывод — в testmon-refresh.log там же. Переменные GIT_*
# хука убираются: иначе git в папке теста пишет в настоящий репозиторий (09.11, клон стал bare).
refresh_testmon_later() {
    command -v flock >/dev/null 2>&1 || return 0
    gitdir=$(git rev-parse --absolute-git-dir)
    (
        for v in $(env | sed -n 's/^\(GIT_[A-Za-z_]*\)=.*/\1/p'); do unset "$v"; done
        unset PYTHONDONTWRITEBYTECODE
        flock -n 9 || exit 0
        nice -n 19 python3 -m pytest -q -n 2 --dist loadfile --testmon --testmon-forceselect \
            -m "not slow" >"$gitdir/testmon-refresh.log" 2>&1
    ) 9>"$gitdir/testmon-refresh.lock" </dev/null >/dev/null 2>&1 &
}
