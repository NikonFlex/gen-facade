"""Слова описания для стаба шага 1: одно правило, названо ли слово в тексте (gf#303).

Текст делится на слова (буквы и цифры); слово из конфига — основа: слово текста совпало, если
начинается с неё и дальше не больше `tail` знаков («кирпич» — «кирпичный», «storey» — «storeys»).
Сочетание из нескольких слов («в два этажа», «two-storey») — подряд идущие слова текста, каждое по
тому же правилу. Этим правилом стаб находит и этажность со стилем (`models/stub.py`), и отделку
(`models/finish.py`).
"""

import re

TOKEN = re.compile(r"[^\W_]+")


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


def named(token: str, stems: list[str], tail: int) -> bool:
    """Слово текста совпало с одной из основ."""
    return any(token.startswith(s) and len(token) - len(s) <= tail for s in stems)


def first[T](text: str, words: dict[T, list[str]], tail: int) -> T | None:
    """Значение, чьё слово или сочетание слов стоит в тексте раньше других; ни одного — None."""
    found = tokens(text)
    phrases = [(tokens(w), value) for value, ws in words.items() for w in ws]
    for i in range(len(found)):
        for phrase, value in phrases:
            if _at(found[i:i + len(phrase)], phrase, tail):
                return value
    return None


def _at(window: list[str], phrase: list[str], tail: int) -> bool:
    if len(window) != len(phrase):
        return False
    return all(named(t, [p], tail) for t, p in zip(window, phrase, strict=True))


def without(text: str, phrases: list[str], tail: int) -> str:
    """Текст без слов, что образуют одно из сочетаний: «one-storey wing» не должно делать
    одноэтажным весь дом при поиске этажности."""
    found, drop = tokens(text), set()
    for i in range(len(found)):
        for phrase in map(tokens, phrases):
            if _at(found[i:i + len(phrase)], phrase, tail):
                drop |= set(range(i, i + len(phrase)))
    return " ".join(t for i, t in enumerate(found) if i not in drop)
