"""Формат листа SVG: общий для записи (svg.py) и разбора (parse.py).

Не настройка, а протокол: лист, записанный с одним значением, не прочитался бы
с другим, поэтому в конфиг не вынесено.
"""

from genfacade.schema import OpeningVariant

SVG_NS = "http://www.w3.org/2000/svg"

FACADE_CLASS = "facade"  # группа одной стороны
SIDE = "data-side"
CLS = "data-cls"         # элемент — rect с классом
ID = "data-id"
FLOOR = "data-floor"
PARENT = "data-parent"
MATERIAL = "data-material"
# Есть — материал в MATERIAL не свой, а зоны под элементом: в JSON у элемента его нет
# (материал элемента — «если отличается от зоны»), а в SVG материал у каждого элемента.
ZONE_MATERIAL = "data-zone-material"
VARIANT = "data-variant"
FIXED = "data-fixed"
ROLE = "data-role"       # зона отделки — polygon с ролью


def num(v: float) -> str:
    """Точное представление числа: разбор должен вернуть то же значение."""
    return repr(float(v))


def encode_variant(v: OpeningVariant) -> str:
    return f"{v.kind}:{v.cols}:{v.rows}"


def decode_variant(text: str) -> OpeningVariant:
    kind, cols, rows = text.split(":")
    return OpeningVariant(kind=kind, cols=int(cols), rows=int(rows))
