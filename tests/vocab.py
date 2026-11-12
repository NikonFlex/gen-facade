"""Отпечаток словаря модели шага 4 — для тестов «поле в условие модели не входит» (gf#454, gf#456,
gf#457): труба, водосток, мансардные окна и дормеры строит код, словарь не меняется."""

import hashlib

from genfacade.train import tokens

FROZEN = (484, "c59f16114f90164d618d12f34991a4a349d24999cdb3606bdaad3ade8e01dcdc")


def fingerprint(cfg) -> tuple[int, str]:
    """Число токенов словаря и sha256 их списка."""
    vocab = tokens.vocabulary(cfg)
    return len(vocab), hashlib.sha256("\n".join(vocab).encode()).hexdigest()
