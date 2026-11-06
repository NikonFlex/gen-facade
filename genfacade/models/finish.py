"""Отделка дома для стаба шага 1 (gf#303): текст → палитра и виды выводимых элементов.

Отделка — именованный набор из `config/models.toml` ([spec.finish.*]): материалы палитры по ролям
с видом и рядом цветов и виды подоконника, наличника, ставен, козырька. Одна на все стены. Выбор:
вид стен — по слову текста, цвет — по слову цвета, а чего в тексте нет — от текста: тот же текст —
тот же дом, без `random`. Модель шага 4 цвет не выбирает, он отсюда (`facade: Цвет из палитры`).
"""

import hashlib
import re
from dataclasses import dataclass, field

from genfacade.config import Finish, SpecStub
from genfacade.schema import HouseTrim, Material, PaletteRole, Trim

WORD = re.compile(r"[^\W\d_]+")


@dataclass(frozen=True)
class Look:
    """Что отделка задаёт дому: палитра по ролям и виды выводимых элементов."""

    finish: str
    materials: list[Material]
    trim: HouseTrim


@dataclass
class Mentions:
    """Что названо в тексте: вид стен, цвета по ролям, элементы (True — есть, False — «без …»)."""

    kind: str | None = None
    colors: dict[PaletteRole, list[set[str]]] = field(default_factory=dict)
    trims: dict[Trim, bool] = field(default_factory=dict)


def look(text: str, style: str, cfg: SpecStub) -> Look:
    """Отделка дома по тексту; описания нет — отделка по умолчанию и первые цвета рядов."""
    tokens = WORD.findall(text.lower())
    mentioned = _mentions(tokens, cfg)
    digest = hashlib.sha256(" ".join(tokens).encode()).digest()
    name = cfg.default_finish if not tokens else _choose(mentioned, style, digest, cfg)
    finish = cfg.finish[name]
    materials = [_material(role, finish, mentioned, digest if tokens else None, cfg)
                 for role in PaletteRole]
    return Look(name, materials, _trim(finish, mentioned.trims, cfg))


def _stem(token: str, stems: list[str], cfg: SpecStub) -> bool:
    """Слово совпало с основой: начинается с неё, и дальше не больше `stem_tail` букв."""
    return any(token.startswith(s) and len(token) - len(s) <= cfg.stem_tail for s in stems)


def _mentions(tokens: list[str], cfg: SpecStub) -> Mentions:
    found = Mentions()
    for i, token in enumerate(tokens):
        if found.kind is None:
            found.kind = next((k for k, ws in cfg.material_words.items()
                               if _stem(token, ws, cfg)), None)
        for trim, words in cfg.trim_words.items():
            if _stem(token, words, cfg):
                found.trims[trim] = not (i and tokens[i - 1] in cfg.negations)
        if names := _color_names(token, cfg):
            role = _role_after(tokens[i + 1:i + 1 + cfg.reach], cfg)
            found.colors.setdefault(role, []).append(names)
    return found


def _color_names(token: str, cfg: SpecStub) -> set[str]:
    return {n for n, c in cfg.colors.items() if _stem(token, c.words, cfg)}


def _role_after(next_tokens: list[str], cfg: SpecStub) -> PaletteRole:
    """Роль, которую красит цвет: по первому слову роли за ним; другой цвет — граница; нет — main"""
    words = _role_words(cfg)
    for token in next_tokens:
        if _color_names(token, cfg):
            break
        for role, stems in words.items():
            if _stem(token, stems, cfg):
                return role
    return PaletteRole.MAIN


def _role_words(cfg: SpecStub) -> dict[PaletteRole, list[str]]:
    """Слова ролей; к роли trim относятся ещё и слова выводимых элементов."""
    words = {role: list(stems) for role, stems in cfg.role_words.items()}
    words.setdefault(PaletteRole.TRIM, []).extend(w for ws in cfg.trim_words.values() for w in ws)
    return words


def _choose(found: Mentions, style: str, digest: bytes, cfg: SpecStub) -> str:
    """Имя отделки: по виду стен, цвету стен и стилю; из оставшихся — от текста."""
    names = [n for n, f in cfg.finish.items()
             if found.kind in (None, f.materials[PaletteRole.MAIN].kind)] or list(cfg.finish)
    wanted = found.colors.get(PaletteRole.MAIN, [])
    names = [n for n in names if _color(cfg.finish[n], PaletteRole.MAIN, wanted, cfg)] or names
    names = [n for n in names if style in cfg.finish[n].styles] or names
    return names[int.from_bytes(digest[:4]) % len(names)]


def _color(finish: Finish, role: PaletteRole, wanted: list[set[str]], cfg: SpecStub) -> str | None:
    """Назван цвет — имя из ряда роли; у стен только оттуда (кирпич не бывает синим), у остальных
    ролей, нет в ряду, — любой цвет ряда colors: «белые наличники» у любой отделки."""
    made = finish.materials[role]
    pool = [*made.colors, *made.extra] if role is PaletteRole.MAIN else [*made.colors, *cfg.colors]
    return next((c for names in wanted for c in pool if c in names), None)


def _material(role: PaletteRole, finish: Finish, found: Mentions, digest: bytes | None,
              cfg: SpecStub) -> Material:
    """Материал роли: назван цвет — он, иначе у стен — от текста, у остальных — первый ряда."""
    row = finish.materials[role].colors
    color = _color(finish, role, found.colors.get(role, []), cfg)
    if color is None:
        by_text = role is PaletteRole.MAIN and digest is not None
        color = row[int.from_bytes(digest[4:8]) % len(row)] if by_text else row[0]
    return Material(id=role.value, kind=finish.materials[role].kind, color=cfg.colors[color].hex)


def _trim(finish: Finish, mentioned: dict[Trim, bool], cfg: SpecStub) -> HouseTrim:
    """Виды элементов отделки; названный в тексте элемент ставится, «без …» — убирается."""
    none = HouseTrim()
    update = {t: cfg.trim_default.kind(t) if on else none.kind(t)
              for t, on in mentioned.items() if on != finish.trim.has(t)}
    return finish.trim.model_copy(update=update)
