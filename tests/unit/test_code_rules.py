"""Правила кода из CLAUDE.md, которые проверяются автоматически."""

import ast
import inspect
from enum import Enum
from pathlib import Path

from genfacade import schema

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "genfacade"
OUR_CODE = [PACKAGE, ROOT / "tests"]
ENUM_VALUES = {
    member.value
    for _, cls in inspect.getmembers(schema, inspect.isclass) if issubclass(cls, Enum)
    for member in cls
}


def _found(folders: list[Path], check) -> list[str]:
    """Нарушения `check(дерево)` → [(строка, что не так)] по всем файлам папок."""
    return [
        f"{path.relative_to(ROOT)}:{line} — {what}"
        for folder in folders for path in sorted(folder.rglob("*.py"))
        for line, what in check(ast.parse(path.read_text(), filename=str(path)))
    ]


def _aliases(tree: ast.AST) -> list[tuple[int, str]]:
    return [
        (node.lineno, f"{name.name} as {name.asname}")
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in node.names
        if name.asname is not None
    ]


def _strings(node: ast.AST) -> list[str]:
    """Строковые константы выражения: само значение или элементы кортежа, списка, множества."""
    items = node.elts if isinstance(node, ast.Tuple | ast.List | ast.Set) else [node]
    return [i.value for i in items if isinstance(i, ast.Constant) and isinstance(i.value, str)]


def _string_literal_types(tree: ast.AST) -> list[tuple[int, str]]:
    """`Literal["a", "b"]` — закрытый набор строками вместо enum."""
    return [
        (node.lineno, f"Literal{_strings(node.slice)}")
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript) and getattr(node.value, "id", "") == "Literal"
        and _strings(node.slice)
    ]


def _compared_with_enum_value(tree: ast.AST) -> list[tuple[int, str]]:
    """`x == "window"`, `x in ("window", "door")` — значение enum из schema.py строкой."""
    return [
        (node.lineno, f"сравнение со строкой {text!r}")
        for node in ast.walk(tree) if isinstance(node, ast.Compare)
        for side in [node.left, *node.comparators]
        for text in _strings(side) if text in ENUM_VALUES
    ]


def test_no_import_aliases():
    # Хозяин 29.09: без сокращений вроде `import xml.etree.ElementTree as ET`.
    found = _found(OUR_CODE, _aliases)
    assert not found, "сокращения при импорте:\n" + "\n".join(found)


def test_closed_sets_are_enums():
    # Хозяин 01.10: закрытый набор значений — enum, а не строки. В тестах сравнение со строкой
    # остаётся там, где читается записанный JSON, поэтому проверяется только пакет.
    found = _found([PACKAGE], _string_literal_types)
    found += _found([PACKAGE], _compared_with_enum_value)
    assert not found, "строки вместо enum:\n" + "\n".join(found)
