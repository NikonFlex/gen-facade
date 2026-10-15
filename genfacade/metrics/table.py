"""Таблица метрик (`evaluation: Метрики одной командой`, gf#16): папка листов → строка таблицы.

Папка результатов метода:

    <папка>/<дом>.json   — лист фасадов (FacadeSheet); ответ, который не разобрался, —
                           любой другой JSON, например {"error": "…"}: он считается невалидным

Группы ТЗ без визуального сходства (FID/KID — второй заход) и две свои:
- valid       — доля домов, у которых лист разобран и его SVG читается обратно;
- geometry    — доля домов без ошибок геометрии: выход за стену, пересечение проёмов, SVG;
- plan        — согласованность с планом: проёмы плана на месте, запретные зоны пусты, углы;
- structure   — расстояние Вассерштейна величин стены до эталона в долях разброса эталона,
                среднее по величинам; меньше — ближе к эталону;
- diversity   — среднее расстояние между раскладками случайных пар стен, признаки — в долях
                разброса эталона;
- description — доля выполненных требований описания, видных на чертеже;
- svd         — SVD-метрика Beyond Segmentation, вспомогательная: рядом окна на стену.
Доли — от всех домов папки: неразобранный дом не проходит ни одной проверки.
"""

import json
from pathlib import Path
from statistics import mean, pstdev
from typing import NamedTuple

import numpy
from pydantic import ValidationError

from genfacade.config import Config
from genfacade.metrics import measures
from genfacade.render.svg import sheet_svg
from genfacade.schema import FacadeSheet, Rule, Violation
from genfacade.validate import errors, validate_svg

METRICS = "metrics.json"
GEOMETRY = {Rule.SVG_PARSE, Rule.OUTSIDE, Rule.OVERLAP}
PLAN = {Rule.PLAN_OPENING, Rule.FORBIDDEN, Rule.CORNER}
COLUMNS = ("valid", "geometry", "plan", "structure", "diversity", "description", "svd",
           "windows_per_wall")


class Item(NamedTuple):
    """Дом из папки: лист (None — не разобран) и ошибки валидатора на его SVG."""

    name: str
    sheet: FacadeSheet | None
    errors: list[Violation]


class Reference(NamedTuple):
    """Эталон: значения величин структуры и разброс признаков стен."""

    structure: dict[str, list[float]]
    scale: list[float]


def load(folder: Path, cfg: Config) -> list[Item]:
    return [_item(p, cfg) for p in sorted(folder.glob("*.json")) if p.name != METRICS]


def _item(path: Path, cfg: Config) -> Item:
    try:
        sheet = FacadeSheet.model_validate_json(path.read_text())
    except ValidationError:
        return Item(path.stem, None, [])
    # Проверяется то, что на чертеже: лист рисуется и читается обратно.
    svg = sheet_svg(sheet, cfg, annotations=False)
    return Item(path.stem, sheet, errors(validate_svg(svg, sheet, cfg.checks)))


def reference(items: list[Item]) -> Reference:
    sheets = _sheets(items)
    walls = [measures.features(f, s.spec) for s in sheets for f in s.facades]
    scale = [pstdev(col) or 1.0 for col in zip(*walls, strict=True)] if walls else [1.0] * 5
    return Reference(measures.structure(sheets), scale)


def _sheets(items: list[Item]) -> list[FacadeSheet]:
    return [i.sheet for i in items if i.sheet is not None]


def row(items: list[Item], ref: Reference, cfg: Config) -> dict:
    """Строка таблицы и подробности по папке."""
    n, sheets = len(items), _sheets(items)
    walls = [(f, s.spec) for s in sheets for f in s.facades]
    checks = {name: sum(check(s) for s in sheets) / n
              for name, check in measures.DESCRIPTION.items()} if n else {}
    distances = _structure(sheets, ref, cfg)
    return {
        "count": n,
        "valid": _share(sum(i.sheet is not None and Rule.SVG_PARSE not in _rules(i)
                            for i in items), n),
        "geometry": _share(sum(i.sheet is not None and not _rules(i) & GEOMETRY
                               for i in items), n),
        "plan": _share(sum(i.sheet is not None and not _rules(i) & PLAN for i in items), n),
        "structure": _mean([d for d in distances.values() if d is not None]),
        "diversity": _diversity(walls, ref, cfg),
        "description": _mean(list(checks.values())),
        "svd": _mean([measures.svd_score(f, spec, cfg.metrics.svd) for f, spec in walls]),
        "windows_per_wall": _mean([len(measures.windows(f)) for f, _ in walls]),
        "details": {"structure": distances, "description": checks,
                    "errors": _counts(items)},
    }


def _rules(item: Item) -> set[Rule]:
    return {v.rule for v in item.errors}


def _structure(sheets: list[FacadeSheet], ref: Reference, cfg: Config) -> dict:
    """Каждая величина: расстояние до эталона в долях разброса обеих выборок вместе; нет
    значений — None. Разброс одного эталона бывает нулевым (у синтетики верх окон выровнен
    точно), и деление на него раздувает любое отклонение в тысячи раз."""
    ours, out = measures.structure(sheets), {}
    for name, theirs in ref.structure.items():
        if not ours[name] or not theirs:
            out[name] = None
            continue
        d = measures.wasserstein(ours[name], theirs, cfg.metrics.quantile_points)
        out[name] = round(d / (pstdev(ours[name] + theirs) or 1.0), 4)
    return out


def _diversity(walls: list, ref: Reference, cfg: Config) -> float | None:
    if len(walls) < 2:
        return None
    x = numpy.array([measures.features(f, spec) for f, spec in walls]) / ref.scale
    rng = numpy.random.default_rng(cfg.metrics.seed)
    pairs = measures.pairs(len(x), cfg.metrics.pairs, rng)
    return round(float(numpy.mean([numpy.linalg.norm(x[i] - x[j]) for i, j in pairs])), 4)


def _counts(items: list[Item]) -> dict:
    out: dict[str, int] = {"unparsed": sum(i.sheet is None for i in items)}
    for i in items:
        for rule in _rules(i):
            out[rule] = out.get(rule, 0) + 1
    return out


def _share(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def _mean(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def run(folders: list[Path], ref_folder: Path, cfg: Config, out: Path) -> Path:
    """Строка на папку против эталона из ref_folder → metrics.json в out и таблица в консоль."""
    ref = reference(load(ref_folder, cfg))
    report = {"reference": str(ref_folder),
              "rows": {str(f): row(load(f, cfg), ref, cfg) for f in folders}}
    out.mkdir(parents=True, exist_ok=True)
    (out / METRICS).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(table(report))
    return out / METRICS


def table(report: dict) -> str:
    """Строки таблицы для консоли: папка и колонки COLUMNS."""
    names = list(report["rows"])
    width = max(len(n) for n in names) + 2
    lines = ["папка".ljust(width) + "".join(c.rjust(17) for c in COLUMNS)]
    for name in names:
        r = report["rows"][name]
        lines.append(name.ljust(width) + "".join(str(r[c]).rjust(17) for c in COLUMNS))
    return "\n".join(lines)
