"""Запись разметки (`manual.Markup`) обратно в TOML того же формата, что пишет разметчик (gf#348).

Страница правки меняет рамки, а не формат: сборщик `genfacade manual` читает записанный файл
без правок. Комментарии шапки (откуда дом, как снят масштаб) сохраняются как есть — это
происхождение разметки, комментарии в конце строк остаются у тех же полей и неизменных элементов
(сведения с чертежа: материал, отметки цоколя, размер окна); поля, равные умолчанию схемы,
не пишутся, как и у разметчика.
"""

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from genfacade.datasets.manual import Markup

INDENT = "  "
ONE_LINE = 100  # список скаляров короче этого — в строку, длиннее — по элементу на строку


def header(text: str) -> str:
    """Комментарии до первого поля: происхождение разметки."""
    lines = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines)


def scalar(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, int):
        return str(v)
    return json.dumps(v, ensure_ascii=False)  # строка TOML: те же экранирования, что в JSON


def inline(v: object) -> str:
    if isinstance(v, Mapping):
        return "{ " + ", ".join(f"{k} = {inline(x)}" for k, x in v.items()) + " }"
    if isinstance(v, Sequence) and not isinstance(v, str):
        return "[" + ", ".join(inline(x) for x in v) + "]"
    return scalar(v)


def value(v: object) -> str:
    """Список таблиц или многоугольников — по элементу на строку, короткий список — в строку."""
    if not isinstance(v, list):
        return inline(v)
    flat = inline(v)
    if len(flat) <= ONE_LINE and not any(isinstance(x, Mapping) for x in v):
        return flat
    return "[\n" + "".join(f"{INDENT}{inline(x)},\n" for x in v) + "]"


HOUSE = -1  # область комментариев: поля дома; у стороны — её номер в `[[sides]]`
Key = tuple[int, str, str]  # (область, поле, элемент списка; "" — сама строка поля)


def split_comment(line: str) -> tuple[str, str]:
    """Строка без комментария в конце и сам комментарий; `#` внутри кавычек — не комментарий."""
    quoted = False
    for i, ch in enumerate(line):
        quoted ^= ch == '"'
        if ch == "#" and not quoted:
            return line[:i].strip(), line[i:].strip()
    return line.strip(), ""


def comments(text: str) -> dict[Key, str]:
    """Комментарии в конце строк: у поля дома или стороны, у элемента его многострочного списка."""
    found: dict[Key, str] = {}
    scope, field = HOUSE, ""
    for line in text.splitlines():
        code, note = split_comment(line)
        if code == "[[sides]]":
            scope, field = scope + 1 if scope != HOUSE else 0, ""
            continue
        named = re.match(r"(\w+) = (.*)", code)
        field, item = (named[1], "") if named else (field, code.rstrip(","))
        if note and (named or item not in ("", "]")):
            found[(scope, field, item)] = note
    return found


def table(fields: Mapping[str, object], scope: int, notes: dict[Key, str]) -> list[str]:
    """Поля таблицы; их комментарии берутся из `notes` и вычёркиваются оттуда."""
    lines = []
    for k, v in fields.items():
        for i, text in enumerate(value(v).split("\n")):
            note = notes.pop((scope, k, "" if i == 0 else text.strip().rstrip(",")), "")
            lines.append((f"{k} = {text}" if i == 0 else text) + (f"  {note}" if note else ""))
    return lines


def orphans(notes: dict[Key, str], scope: int) -> list[str]:
    """Комментарии, чьё поле или элемент изменились: строками над таблицей, а не потерянными."""
    return [notes.pop(k) for k in [k for k in notes if k[0] == scope]]


def dumps(m: Markup, head: str = "", old: str = "") -> str:
    """Разметка как TOML: шапка, поля дома, затем `[[sides]]` по порядку.

    Комментарии в конце строк берутся из прежнего текста файла `old` и остаются у тех же полей и
    неизменных элементов; у изменённых и пропавших — строкой над таблицей.
    """
    data = m.model_dump(mode="json", exclude_defaults=True)
    sides = data.pop("sides")
    notes = comments(old)
    house = table(data, HOUSE, notes)
    tables = [table(side, n, notes) for n, side in enumerate(sides)]
    lines = [head] if head else []
    gone = [notes.pop(k) for k in [*notes] if k[0] >= len(sides)]  # сторона, которой больше нет
    lines += [*orphans(notes, HOUSE), *gone, *house]
    for n, fields in enumerate(tables):
        lines += ["", *orphans(notes, n), "[[sides]]", *fields]
    return "\n".join(lines) + "\n"


def write(path: Path, m: Markup) -> None:
    """Файл заменяется целиком готовым: оборванная запись не оставит полфайла."""
    old = path.read_text() if path.exists() else ""
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(dumps(m, header(old), old))
    tmp.replace(path)
