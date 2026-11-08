"""Отделка дома для стаба шага 1 (gf#303): текст → палитра и виды выводимых элементов.

Отделка — именованный набор из `config/models.toml` ([spec.finish.*]): материалы палитры по ролям
с видом и рядом цветов и виды подоконника, наличника, ставен, козырька. Одна на все стены. Выбор:
вид стен — по слову текста, цвет — по слову цвета, а чего в тексте нет — от текста: тот же текст —
тот же дом, без `random`. Модель шага 4 цвет не выбирает, он отсюда (`facade: Цвет из палитры`).
"""

import hashlib
from dataclasses import dataclass, field

from genfacade.config import Finish, SpecStub
from genfacade.models import words
from genfacade.schema import HouseTrim, Material, PaletteRole, RoofKind, Trim


@dataclass(frozen=True)
class Look:
    """Что отделка задаёт дому: палитра по ролям, виды выводимых элементов и вид крыши."""

    finish: str
    materials: list[Material]
    trim: HouseTrim
    roof: RoofKind


@dataclass
class Mentions:
    """Что названо в тексте: виды стен (слово может называть несколько), цвета по ролям,
    элементы (True — есть, False — «без …»)."""

    kinds: set[str] | None = None
    colors: dict[PaletteRole, list[set[str]]] = field(default_factory=dict)
    trims: dict[Trim, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Pick:
    """Чем выбирается цвет, которого в тексте нет: хеш текста и сочетание цветов (gf#317)."""

    digest: bytes | None
    scheme: dict[PaletteRole, str]


def look(text: str, style: str, cfg: SpecStub) -> Look:
    """Отделка дома по тексту; описания нет — отделка по умолчанию и первые цвета рядов."""
    tokens = words.tokens(text)
    mentioned = _mentions(tokens, cfg)
    digest = hashlib.sha256(" ".join(tokens).encode()).digest()
    name = cfg.default_finish if not tokens else _choose(mentioned, style, digest, cfg)
    finish = cfg.finish[name]
    scheme = _scheme(finish, mentioned, digest, cfg) if tokens else {}
    pick = Pick(digest if tokens else None, scheme)
    materials = [_material(role, finish, mentioned, pick, cfg) for role in PaletteRole]
    return Look(name, materials, _trim(finish, mentioned.trims, cfg), finish.roof)


def _stem(token: str, stems: list[str], cfg: SpecStub) -> bool:
    return words.named(token, stems, cfg.stem_tail)


def _mentions(tokens: list[str], cfg: SpecStub) -> Mentions:
    found = Mentions()
    for i, token in enumerate(tokens):
        named = {k for k, ws in cfg.material_words.items() if _stem(token, ws, cfg)}
        named |= {k for k, g in cfg.material_like.items() if g in named}
        # слово «кирпич» называет все кирпичи, а «полуторный» после него сужает до одного;
        # слово другого вида, чем первое найденное, стены не меняет
        found.kinds = named or None if found.kinds is None else (found.kinds & named or found.kinds)
        for trim, stems in cfg.trim_words.items():
            if _stem(token, stems, cfg):
                found.trims[trim] = not (i and tokens[i - 1] in cfg.negations)
        if names := _color_names(token, cfg):
            role = _role_after(tokens[i + 1:i + 1 + cfg.reach], cfg)
            found.colors.setdefault(role, []).append(names)
    return found


def _color_names(token: str, cfg: SpecStub) -> set[str]:
    return {n for n, c in cfg.colors.items() if _stem(token, c.words, cfg)}


def _role_after(next_tokens: list[str], cfg: SpecStub) -> PaletteRole:
    """Роль, которую красит цвет: по первому слову роли за ним; другой цвет — граница; нет — main"""
    roles = _role_words(cfg)
    for token in next_tokens:
        if _color_names(token, cfg):
            break
        for role, stems in roles.items():
            if _stem(token, stems, cfg):
                return role
    return PaletteRole.MAIN


def _role_words(cfg: SpecStub) -> dict[PaletteRole, list[str]]:
    """Слова ролей; к роли trim относятся ещё и слова выводимых элементов."""
    roles = {role: list(stems) for role, stems in cfg.role_words.items()}
    roles.setdefault(PaletteRole.TRIM, []).extend(w for ws in cfg.trim_words.values() for w in ws)
    return roles


def _choose(found: Mentions, style: str, digest: bytes, cfg: SpecStub) -> str:
    """Имя отделки: по виду стен, цвету стен и стилю; из оставшихся — от текста."""
    names = [n for n, f in cfg.finish.items() if found.kinds is None
             or f.materials[PaletteRole.MAIN].kind in found.kinds] or list(cfg.finish)
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


def _scheme(finish: Finish, found: Mentions, digest: bytes,
            cfg: SpecStub) -> dict[PaletteRole, str]:
    """Сочетание цветов отделки от текста; назван цвет стен — среди сочетаний с таким цветом
    стен, и нет такого — сочетания нет (цвет назван, а не выбран)."""
    wanted = _color(finish, PaletteRole.MAIN, found.colors.get(PaletteRole.MAIN, []), cfg)
    pool = [cfg.schemes[n].colors for n in finish.schemes
            if wanted in (None, cfg.schemes[n].colors[PaletteRole.MAIN])]
    return pool[int.from_bytes(digest[8:12]) % len(pool)] if pool else {}


def _material(role: PaletteRole, finish: Finish, found: Mentions, pick: Pick,
              cfg: SpecStub) -> Material:
    """Материал роли: назван цвет — он, иначе цвет сочетания, иначе у стен — от текста, у
    остальных — первый ряда."""
    row = finish.materials[role].colors
    color = _color(finish, role, found.colors.get(role, []), cfg) or pick.scheme.get(role)
    if color is None:
        by_text = role is PaletteRole.MAIN and pick.digest is not None
        color = row[int.from_bytes(pick.digest[4:8]) % len(row)] if by_text else row[0]
    return Material(id=role.value, kind=finish.materials[role].kind, color=cfg.colors[color].hex)


def _trim(finish: Finish, mentioned: dict[Trim, bool], cfg: SpecStub) -> HouseTrim:
    """Виды элементов отделки; названный в тексте элемент ставится, «без …» — убирается."""
    none = HouseTrim()
    update = {t: cfg.trim_default.kind(t) if on else none.kind(t)
              for t, on in mentioned.items() if on != finish.trim.has(t)}
    return finish.trim.model_copy(update=update)
