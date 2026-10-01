"""Примеры на диске: файл на дом и опись источника (specs/data.md, правило 10).

    <корень>/<источник>/<id>.json        Sample
    <корень>/<источник>/_manifest.json   опись: сколько примеров, разбиение, стены, классы

Служебные файлы источника начинаются с «_» — имя примера так начинаться не может.
"""

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from genfacade.pipeline import git_sha
from genfacade.schema import Sample, Source
from genfacade.validate import OPENINGS

MANIFEST = "_manifest.json"


def path(root: Path, source: Source, sample_id: str) -> Path:
    return root / source / f"{sample_id}.json"


def write(sample: Sample, root: Path) -> Path:
    out = path(root, sample.source, sample.id)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Сначала рядом, потом переименование: сборку могут оборвать посреди записи, а готовый
    # файл при продолжении считается целым.
    draft = out.with_suffix(".part")
    draft.write_text(sample.model_dump_json(indent=2))
    os.replace(draft, out)
    return out


def read(root: Path, source: Source, sample_id: str) -> Sample:
    return Sample.model_validate_json(path(root, source, sample_id).read_text())


def ids(root: Path, source: Source) -> list[str]:
    """Имена примеров источника по алфавиту; служебные файлы — не примеры."""
    return sorted(p.stem for p in (root / source).glob("*.json") if not p.name.startswith("_"))


def manifest(root: Path, source: Source) -> dict:
    """Опись источника — считается по файлам примеров, а не ведётся отдельно."""
    samples = [read(root, source, i) for i in ids(root, source)]
    facades = [f for s in samples for f in s.sheet.facades]
    return {
        "source": source,
        "samples": len(samples),
        "splits": dict(Counter(s.split for s in samples)),
        "walls": len(facades),
        # глухие стены синтетика делает намеренно — их доля видна здесь (data.md, правило 1)
        "blind_walls": sum(not any(e.cls in OPENINGS for e in f.elements) for f in facades),
        "elements": dict(Counter(e.cls for f in facades for e in f.elements)),
        "date": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(),
    }


def write_manifest(root: Path, source: Source, extra: dict | None = None) -> Path:
    """Сохранить опись; extra — что знает только сборщик источника (настройки, отброшенное)."""
    out = root / source / MANIFEST
    out.write_text(json.dumps(manifest(root, source) | (extra or {}), ensure_ascii=False,
                              indent=2))
    return out


def load_manifest(root: Path, source: Source) -> dict:
    """Сохранённая опись, если она про нынешние файлы; иначе — посчитанная заново."""
    saved = root / source / MANIFEST
    if saved.exists():
        data = json.loads(saved.read_text())
        if data["samples"] == len(ids(root, source)):
            return data
    return manifest(root, source)
