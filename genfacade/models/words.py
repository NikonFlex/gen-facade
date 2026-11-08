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


def phrase_at(tokens_: list[str], i: int, phrases: list[str], tail: int) -> bool:
    """С i-го слова текста начинается одно из сочетаний слов (основы, как в `named`)."""
    return any(at(tokens_[i:i + len(p)], p, tail) for p in map(tokens, phrases))


def first[T](text: str, words: dict[T, list[str]], tail: int) -> T | None:
    """Значение, чьё слово или сочетание слов стоит в тексте раньше других; ни одного — None."""
    found = tokens(text)
    phrases = [(tokens(w), value) for value, ws in words.items() for w in ws]
    for i in range(len(found)):
        for phrase, value in phrases:
            if at(found[i:i + len(phrase)], phrase, tail):
                return value
    return None


def at(window: list[str], phrase: list[str], tail: int) -> bool:
    if len(window) != len(phrase):
        return False
    return all(named(t, [p], tail) for t, p in zip(window, phrase, strict=True))
