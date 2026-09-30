"""Шаг 1 до модели: описание на английском → HouseSpec по словарю (generation.md, п. 2).

Базовый подход для сравнения с моделью. Словари и значения по умолчанию — config/spec.toml.
Для каждого поля запоминаем, какая фраза сработала; None — поле взято по умолчанию.
Ось конька правило не знает: она зависит от плана, её ставит конвейер (pipeline.py).
"""

import re

from genfacade.config import SpecRule
from genfacade.schema import HouseSpec, Material, Roof

Found = dict[str, str | None]  # поле → найденная фраза; None — по умолчанию


def from_text(text: str, rule: SpecRule) -> tuple[HouseSpec, Found]:
    found: Found = {}
    d = rule.defaults
    apartment = _search(rule.words.apartment, text)
    found["building_type"] = apartment
    building = "apartment" if apartment else d.building_type
    floors = _floors(text, rule, building, found)
    level, found["height"] = _choice(text, rule.words.height, d.height)
    height = rule.floor_height_m[level]
    styles = {k: s.words for k, s in rule.styles.items()}
    style, found["style"] = _choice(text, styles, d.style)
    default_roof = d.apartment_roof if apartment else rule.styles[style].roof
    roof, found["roof"] = _choice(text, rule.words.roof, default_roof)
    spec = HouseSpec(
        building_type=building, floors=floors, floor_heights_m=[height] * floors,
        plinth_m=d.plinth_m, eaves_m=d.plinth_m + height * floors,
        roof=Roof(kind=roof, pitch_deg=rule.pitch_deg[roof], overhang_m=d.overhang_m,
                  material="roof"),
        style=style, materials=_palette(text, rule, style, found),
    )
    return spec, found


def _search(patterns: list[str], text: str) -> str | None:
    """Первая найденная фраза по списку шаблонов, целыми словами, без учёта регистра."""
    for p in patterns:
        m = re.search(rf"\b(?:{p})\b", text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def _choice(text: str, options: dict[str, list[str]], default: str) -> tuple[str, str | None]:
    """Первый вариант, чей шаблон нашёлся в тексте, и фраза; иначе — по умолчанию и None."""
    for key, patterns in options.items():
        phrase = _search(patterns, text)
        if phrase:
            return key, phrase
    return default, None


def _floors(text: str, rule: SpecRule, building: str, found: Found) -> int:
    one = _search(rule.words.one_floor, text)
    if one:
        found["floors"] = one
        return 1
    pattern = rule.words.floors.replace("{numbers}", "|".join(rule.numbers))
    m = re.search(rf"\b{pattern}\b", text, re.IGNORECASE)
    found["floors"] = m.group(0) if m else None
    if m is None:
        d = rule.defaults
        return d.apartment_floors if building == "apartment" else d.cottage_floors
    n = m.group(1).lower()
    return int(n) if n.isdigit() else rule.numbers[n]


def _palette(text: str, rule: SpecRule, style: str, found: Found) -> list[Material]:
    """Палитра стиля по ролям; материал, названный в тексте, заменяет вид своей роли."""
    materials = []
    for role, kind in rule.styles[style].palette.items():
        named, found[f"material.{role}"] = _choice(text, rule.materials.get(role, {}), kind)
        materials.append(Material(id=role, kind=named))
    return materials
