"""Запись файла STEP (ISO 10303-21) для IFC4: сущности по порядку, ссылки `#n`, строки, enum.

Своя запись, а не IfcOpenShell: нужны два десятка видов сущностей, а библиотека — LGPL-3 с
бинарным колесом на каждую версию Python и ОС (docs/tasks/gf-0392.md, разведка). Файл читают
IfcOpenShell, web-ifc и любой просмотрщик IFC4.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

GUID_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
GUID_LEN = 22
GUID_BITS = 6
ASCII_MAX = 0x7E


@dataclass(frozen=True)
class Ref:
    """Ссылка на сущность файла: `#номер`."""

    number: int


class Enum(str):
    """Значение перечисления IFC: `.NAME.`, а не строка в кавычках."""


class Star(str):
    """Звёздочка STEP: производный атрибут `*`."""


STAR = Star("*")


@dataclass(frozen=True)
class Typed:
    """Значение со своим типом IFC: `IFCLABEL('x')`, `IFCBOOLEAN(.T.)`."""

    kind: str
    v: object


def guid(name: str) -> str:
    """GlobalId IFC (22 знака) из имени: один и тот же дом даёт один и тот же файл."""
    number = uuid.uuid5(uuid.NAMESPACE_URL, name).int
    digits = [GUID_ALPHABET[(number >> (GUID_BITS * k)) & (len(GUID_ALPHABET) - 1)]
              for k in range(GUID_LEN)]
    return "".join(reversed(digits))


def text(value: str) -> str:
    """Строка STEP: апостроф и обратная косая удваиваются, не-ASCII — `\\X2\\hhhh\\X0\\`."""
    out, wide = [], []

    def flush() -> None:
        if wide:
            out.append("\\X2\\" + "".join(f"{ord(c):04X}" for c in wide) + "\\X0\\")
            wide.clear()

    for c in value:
        if ord(c) > ASCII_MAX or ord(c) < ord(" "):
            wide.append(c)
            continue
        flush()
        out.append(c * 2 if c in "'\\" else c)
    flush()
    return "'" + "".join(out) + "'"


def value(v: object) -> str:
    """Атрибут сущности: None — `$`, bool — `.T.`, число, строка, Ref, Enum, список — `(…)`."""
    if v is None:
        return "$"
    if isinstance(v, Ref):
        return f"#{v.number}"
    if isinstance(v, Typed):
        return f"{v.kind.upper()}({value(v.v)})"
    if isinstance(v, Star):
        return str(v)
    if isinstance(v, Enum):
        return f".{v}."
    if isinstance(v, bool):
        return ".T." if v else ".F."
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.6f}"
    if isinstance(v, str):
        return text(v)
    return "(" + ",".join(value(x) for x in v) + ")"


class Step:
    """Файл STEP: `add` дописывает сущность и возвращает ссылку на неё."""

    def __init__(self, schema: str, name: str, author: str):
        self.schema, self.name, self.author = schema, name, author
        self.lines: list[str] = []

    def add(self, entity: str, *attrs: object) -> Ref:
        body = ",".join(map(value, attrs))
        self.lines.append(f"#{len(self.lines) + 1}={entity.upper()}({body});")
        return Ref(len(self.lines))

    def render(self) -> str:
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        head = [
            "ISO-10303-21;", "HEADER;",
            "FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');",
            f"FILE_NAME({text(self.name)},'{stamp}',({text(self.author)}),(''),"
            f"{text(self.author)},{text(self.author)},'');",
            f"FILE_SCHEMA(('{self.schema}'));", "ENDSEC;", "DATA;"]
        return "\n".join([*head, *self.lines, "ENDSEC;", "END-ISO-10303-21;", ""])
