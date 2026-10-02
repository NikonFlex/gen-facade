"""Корпус для обучения: дома источника → номера токенов одним файлом (gf#73).

    <корень>/<источник>/_tokens.npz    массивы: все последовательности подряд и их границы
    <корень>/<источник>/_tokens.json   опись: сколько, длины, словарь, пропущенные дома

Каждый дом записан в каждом режиме: дом один, а условие и пометки заданных полей — разные
(train/tokens.py). Последовательность — условие и ответ вместе; где кончается условие,
видно по токену `<answer>`. Часть (`train` / `val`) — та же, что у дома.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import numpy

from genfacade.config import Config
from genfacade.datasets import store
from genfacade.pipeline import git_sha
from genfacade.schema import Mode, Source, Split
from genfacade.train import tokens
from genfacade.train.tokens import TokenError

ARRAYS = "_tokens.npz"
MANIFEST = "_tokens.json"
# В массивах часть и режим — номером в этих списках.
SPLITS, MODES = list(Split), list(Mode)
ID_TYPE = numpy.uint16  # номер токена; словарь больше не помещается — отказ, не обрезка


class CorpusError(ValueError):
    """Корпус не собирается; текст — причина."""


class Row(NamedTuple):
    """Одна последовательность: дом в одном режиме."""

    sample: str
    split: Split
    mode: Mode
    ids: list[int]


def build(source: Source, cfg: Config) -> Path:
    """Записать все дома источника токенами; вернуть путь к описи."""
    root = cfg.data.paths.samples_dir
    words = tokens.vocabulary(cfg)
    if len(words) > numpy.iinfo(ID_TYPE).max + 1:
        raise CorpusError(f"словарь {len(words)} токенов не помещается в {ID_TYPE.__name__}")
    number = {word: i for i, word in enumerate(words)}
    rows: list[Row] = []
    skipped: dict[str, str] = {}
    for name in store.ids(root, source):
        sample = store.read(root, source, name)
        try:  # дом, который не записывается хотя бы в одном режиме, не берём ни в одном
            rows += [Row(name, sample.split, mode,
                         [number[t] for t in tokens.encode(sample.sheet, mode, cfg)])
                     for mode in MODES]
        except TokenError as e:
            skipped[name] = str(e)
    if not rows:
        raise CorpusError(f"в {root / source} нет домов, которые записываются токенами")
    _save_arrays(rows, words, root / source / ARRAYS)
    out = root / source / MANIFEST
    out.write_text(json.dumps(_manifest(rows, skipped, cfg) | {"source": source},
                              ensure_ascii=False, indent=2))
    return out


def _save_arrays(rows: list[Row], words: list[str], out: Path) -> None:
    lengths = [len(r.ids) for r in rows]
    numpy.savez_compressed(
        out,
        ids=numpy.concatenate([numpy.asarray(r.ids, dtype=ID_TYPE) for r in rows]),
        ends=numpy.cumsum(lengths),  # последовательность i — ids[ends[i-1]:ends[i]]
        split=numpy.asarray([SPLITS.index(r.split) for r in rows], dtype=numpy.uint8),
        mode=numpy.asarray([MODES.index(r.mode) for r in rows], dtype=numpy.uint8),
        sample=numpy.asarray([r.sample for r in rows]),
        vocabulary=numpy.asarray(words),
    )


def _manifest(rows: list[Row], skipped: dict[str, str], cfg: Config) -> dict:
    lengths = sorted(len(r.ids) for r in rows)
    return {
        "houses": len({r.sample for r in rows}),
        "sequences": len(rows),
        "tokens": sum(lengths),
        "by_split": {s: sum(r.split is s for r in rows) for s in SPLITS},
        "by_mode": {m: sum(r.mode is m for r in rows) for m in MODES},
        # самая длинная последовательность задаёт окно модели
        "length": {"min": lengths[0], "median": lengths[len(lengths) // 2], "max": lengths[-1]},
        "vocabulary": len(tokens.vocabulary(cfg)),
        "splits": SPLITS,
        "modes": MODES,
        "config": cfg.tokens.model_dump(mode="json"),
        "skipped": skipped,
        "date": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(),
    }
