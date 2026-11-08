"""Запись разметки (`manual.Markup`) обратно в TOML того же формата, что пишет разметчик (gf#348).

Страница правки меняет рамки, а не формат: сборщик `genfacade manual` читает записанный файл
без правок. Комментарии шапки (откуда дом, как снят масштаб) сохраняются как есть — это
происхождение разметки; поля, равные умолчанию схемы, не пишутся, как и у разметчика.
"""

import json
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


def table(fields: Mapping[str, object]) -> list[str]:
    return [f"{k} = {value(v)}" for k, v in fields.items()]


def dumps(m: Markup, head: str = "") -> str:
    """Разметка как TOML: шапка, поля дома, затем `[[sides]]` по порядку."""
    data = m.model_dump(mode="json", exclude_defaults=True)
    sides = data.pop("sides")
    lines = [head] if head else []
    lines += table(data)
    for side in sides:
        lines += ["", "[[sides]]", *table(side)]
    return "\n".join(lines) + "\n"


def write(path: Path, m: Markup, head: str) -> None:
    """Файл заменяется целиком готовым: оборванная запись не оставит полфайла."""
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(dumps(m, head))
    tmp.replace(path)
