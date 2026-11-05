"""Приборы и сторожа: то, что решается в одном месте, там и решается (gf#293, чистый контур C5/C9).

Копия правила в соседнем скрипте расходится при первой правке: слово закрытия в теле PR и в
заголовке, служебные файлы папки задач, номер задачи из имени ветки или файла, исход прогона.
Тест читает исходники `tools/` и `.agents/guards/` и падает, если кусок правила снова стоит
вне своего файла. Поведение каждого правила проверяют `--selftest` приборов.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted([*(ROOT / "tools").glob("*.py"), *(ROOT / ".agents/guards").glob("*.py")])

#: Строка, с которой код сравнивает (`==`, `in {…}`) → файлы, где ей можно стоять в сравнении.
COMPARED = {
    "index.md": {"backlog.py"},
    "review.md": {"backlog.py"},
    "not_planned": {"backlog.py"},
    "прошёл": set(),      # итог сценария сравнивают с RunResult, не со строкой
    "не прошёл": set(),
}
#: Кусок регулярного выражения или пути в любой строке кода (кроме docstring) → единственный файл.
WRITTEN = {
    "close[sd]?": {"pr_link.py"},                 # слово закрытия: тело PR, заголовок, коммит
    "(\\d+)-": {"project_config.py"},             # номер задачи из имени ветки: `12-parser`
    "[a-z]+-(\\d+)": {"backlog.py"},              # номер задачи из имени файла задачи
    "--absolute-git-dir": set(),                  # git-каталог клона — project_config.git_dir
    "*-{": set(),                                 # glob `*-{n:04d}.md` — вместо backlog.task_path
}


def docstrings(tree: ast.AST) -> set[int]:
    found = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant):
            found.add(id(body[0].value))
    return found


def strings_of(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant)
            and isinstance(n.value, str)]


def stray(table: dict[str, set[str]], texts) -> list[str]:
    """Файлы и фрагменты из table, найденные там, где им стоять нельзя."""
    out = []
    for path in SOURCES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for text in texts(tree):
            out += [f"{path.name}: «{key}» в {text!r} — объявлено в {sorted(allowed) or 'нигде'}"
                    for key, allowed in table.items()
                    if key in text.casefold() and path.name not in allowed]
    return out


def compared(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            yield from strings_of(node)


def written(tree: ast.AST):
    skip = docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in skip:
            yield node.value
        elif isinstance(node, ast.JoinedStr):
            yield ast.unparse(node)  # f-строка целиком: `*-{n:04d}.md` — не по кускам


def test_literals_are_not_compared_outside_their_file():
    assert not stray(COMPARED, compared)


def test_rule_fragments_are_written_once():
    assert not stray(WRITTEN, written)
