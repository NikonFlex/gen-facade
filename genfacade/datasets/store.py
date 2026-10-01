"""Примеры на диске: файл на дом и опись источника (specs/data.md, правило 10).

    <корень>/<источник>/<id>.json        Sample
    <корень>/<источник>/_manifest.json   опись: сколько примеров, разбиение, стены, классы
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from genfacade.pipeline import git_sha
from genfacade.schema import Sample, Source

MANIFEST = "_manifest.json"


def path(root: Path, source: Source, sample_id: str) -> Path:
    return root / source / f"{sample_id}.json"


def write(sample: Sample, root: Path) -> Path:
    out = path(root, sample.source, sample.id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(sample.model_dump_json(indent=2))
    return out


def read(root: Path, source: Source, sample_id: str) -> Sample:
    return Sample.model_validate_json(path(root, source, sample_id).read_text())


def ids(root: Path, source: Source) -> list[str]:
    """Имена примеров источника по алфавиту; опись — не пример."""
    return sorted(p.stem for p in (root / source).glob("*.json") if p.name != MANIFEST)


def manifest(root: Path, source: Source) -> dict:
    """Опись источника — считается по файлам примеров, а не ведётся отдельно."""
    samples = [read(root, source, i) for i in ids(root, source)]
    facades = [f for s in samples for f in s.sheet.facades]
    return {
        "source": source,
        "samples": len(samples),
        "splits": dict(Counter(s.split for s in samples)),
        "walls": len(facades),
        "elements": dict(Counter(e.cls for f in facades for e in f.elements)),
        "date": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(),
    }


def write_manifest(root: Path, source: Source) -> Path:
    out = root / source / MANIFEST
    out.write_text(json.dumps(manifest(root, source), ensure_ascii=False, indent=2))
    return out
