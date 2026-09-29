"""Правила кода из CLAUDE.md, которые проверяются автоматически."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUR_CODE = [ROOT / "genfacade", ROOT / "tests"]


def _aliases(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        f"{path.relative_to(ROOT)}:{node.lineno} — {name.name} as {name.asname}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in node.names
        if name.asname is not None
    ]


def test_no_import_aliases():
    # Хозяин 29.09: без сокращений вроде `import xml.etree.ElementTree as ET`.
    found = [a for folder in OUR_CODE for f in sorted(folder.rglob("*.py")) for a in _aliases(f)]
    assert not found, "сокращения при импорте:\n" + "\n".join(found)
