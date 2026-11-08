"""Источник вида для каталога (gf#354): строки таблиц docs/library-catalog.md по имени вида.

Файл пишут люди, и таблицы в нём разные, поэтому разбор по признакам, а не по номерам колонок:
имя вида — первое слово в обратных кавычках в строке (первая ячейка в приоритете), источник —
ячейка колонки, чей заголовок начинается с «Источник»; в таблице без такой колонки (крыши по
справочнику ДОМ.РФ) — остальные ячейки строки с их заголовками. Нет файла или вида в таблицах —
источника нет, пусто.
"""

import re
from pathlib import Path

NAME = re.compile(r"`([a-z][a-z0-9_]*)`")
SOURCE_HEAD = "Источник"
SKIP_HEAD = ("В модуле",)


def sources(path: Path, headings: list[str], row: str = "") -> dict[str, str]:
    """Имя вида → источник из таблиц под подзаголовками, в названии которых есть один из
    headings; row — кусок первой ячейки строки (отличить подоконник от наличника)."""
    if not path.exists():
        return {}
    found: dict[str, str] = {}
    heading, head = "", None
    for line in path.read_text().splitlines():
        if line.startswith("#"):
            heading, head = line.lstrip("# ").strip(), None
        elif not line.startswith("|"):
            head = None
        elif any(h in heading for h in headings):
            if head is None:
                head = _cells(line)
            elif not set(line) <= set("|-: "):  # строка «|---|---|» под заголовком — не данные
                _row(found, head, _cells(line), row)
    return found


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _row(found: dict[str, str], head: list[str], cells: list[str], row: str) -> None:
    """Строка таблицы → записи по каждому имени вида в первой ячейке (или в строке)."""
    if row not in cells[0] or len(cells) != len(head):
        return
    names = NAME.findall(cells[0]) or NAME.findall(" ".join(cells))[:1]
    text = _source(head, cells)
    for name in names:
        found.setdefault(name, text)


def _source(head: list[str], cells: list[str]) -> str:
    for title, cell in zip(head, cells, strict=True):
        if title.startswith(SOURCE_HEAD):
            return cell.replace("`", "")
    facts = [f"{t}: {c}" for t, c in zip(head, cells, strict=True)
             if c and not t.startswith(SKIP_HEAD)]
    return "; ".join(facts).replace("`", "")
