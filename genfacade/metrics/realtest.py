"""Таблица метрик против реального теста (gf#180, gf#210): эталон — дома ручной разметки, строки —
модель шага 4 (шаги 4–5 конвейера: страж, до attempts попыток; брак — {"error": …}), правило
GenPlan, синтетика val, подмены; калибровка «реальные против реальных» — половина домов против
другой. На машине с torch-fidelity в строках есть FID и KID (`genfacade realtest`, gpu.yml).

    <out>/<режим>/<строка>/<дом>.json   листы
    <out>/<режим>/rows/metrics.json     строки против всех реальных домов
    <out>/<режим>/half/metrics.json     половина реальных против другой
    <out>/summary.md                    сводка: строки обоих режимов, годных листов и колонки
                                        `[realtest] summary` (config/metrics.toml)

Строки моделей (gf#212, сравнение при переобучении — tools/retrain.sh): без `Rows` — модель
config/models.toml, строка `model`; с ними — `model-<имя>` на каждый чекпойнт (ответы — в этом
прогоне) и на каждую папку прошлого прогона (её листы `<режим>/model`): модель другой записи
токенов отвечает только на своём коде, а таблицу обе строки получают одну, этим кодом.
"""

import json
import shutil
from pathlib import Path
from typing import NamedTuple

import numpy

from genfacade import baselines, pipeline
from genfacade.baselines import Baseline
from genfacade.config import Config
from genfacade.metrics import calibrate, table
from genfacade.models.stub import ModelError
from genfacade.schema import FacadeSheet, Mode, Source, Split
from genfacade.train import tokens
from genfacade.train.tokens import bare, given_sides

HALVES = ("half-a", "half-b")
SUBSTITUTES = ("random", "foreign", "empty")
MODEL = "model"
SUMMARY = "summary.md"


class Rows(NamedTuple):
    """Строки моделей: имя → чекпойнт и имя → папка прошлого `genfacade realtest`."""

    models: dict[str, Path]
    sheets: dict[str, Path]


def run(cfg: Config, out: Path, synthetic: int, rows: Rows) -> Path:
    """Листы строк в каждом режиме и таблицы по ним; synthetic — домов синтетики val, 0 — все.
    Модели и папки строк проверяются до долгой работы: чужой словарь — отказ сразу."""
    layouts, sheets = _layouts(cfg, rows.models), _sheets(rows.sheets)
    real = calibrate.houses(Source.MANUAL, Split.TEST, 0, cfg)
    synth = calibrate.houses(Source.SYNTHETIC, Split.VAL, synthetic, cfg)
    for mode in Mode:
        given = {name: given_sides(sheet, mode) for name, sheet in real.items()}
        models = [_answers(given, mode, run_cfg, out / mode / name)
                  for name, run_cfg in layouts.items()]
        models += [_copied(source / mode / MODEL, out / mode / name)
                   for name, source in sheets.items()]
        folders = models + _folders(given, synth, mode, cfg, out / mode)
        table.run(folders, out / mode / calibrate.REFERENCE, cfg, out / mode / "rows")
        table.run([out / mode / HALVES[0]], out / mode / HALVES[1], cfg, out / mode / "half")
    (out / SUMMARY).write_text(summary(out, cfg))
    return out


def _layouts(cfg: Config, models: dict[str, Path]) -> dict[str, Config]:
    """Строка → настройки с её чекпойнтом. Без `--model` — модель config/models.toml, если
    она есть; с ними — каждая, и её словарь — нынешней записи токенов."""
    if not models:
        found = pipeline.trained_model(cfg.models.layout) is not None
        return {MODEL: cfg} if found else {}
    out = {}
    for name, path in models.items():
        settings = cfg.models.layout.model_copy(update={"checkpoint": path})
        model = pipeline.trained_model(settings)
        if model is None:
            raise ModelError(f"нет чекпойнта {path}")
        if model.words != tokens.vocabulary(cfg):
            raise ModelError(f"словарь {path} не совпадает с нынешней записью токенов: листы "
                             "этой модели — её кодом, сюда — папкой прошлого прогона")
        models_cfg = cfg.models.model_copy(update={"layout": settings})
        out[f"{MODEL}-{name}"] = cfg.model_copy(update={"models": models_cfg})
    return out


def _sheets(folders: dict[str, Path]) -> dict[str, Path]:
    """Строка → папка прошлого прогона, в которой есть листы модели в обоих режимах."""
    for folder in folders.values():
        for mode in Mode:
            if not (folder / mode / MODEL).is_dir():
                raise FileNotFoundError(f"нет листов модели {folder / mode / MODEL}")
    return {f"{MODEL}-{name}": folder for name, folder in folders.items()}


def _copied(source: Path, out: Path) -> Path:
    """Листы прошлого прогона — копией: папка запуска полна сама по себе."""
    shutil.copytree(source, out, dirs_exist_ok=True)
    return out


def _folders(given: dict, synth: dict, mode: Mode, cfg: Config, out: Path) -> list[Path]:
    """Эталон, половины, синтетика, правило GenPlan и подмены — строки без модели; given —
    реальные дома с условием режима."""
    names, sheets = list(given), list(given.values())
    rng = numpy.random.default_rng(cfg.metrics.seed)
    calibrate.write(out / calibrate.REFERENCE, names, sheets)
    first = set(rng.permutation(names)[: len(names) // 2])
    for part, keep in zip(HALVES, (True, False), strict=True):
        pick = [(n, s) for n, s in zip(names, sheets, strict=True) if (n in first) == keep]
        calibrate.write(out / part, [n for n, _ in pick], [s for _, s in pick])
    calibrate.write(out / "generator", list(synth), [given_sides(s, mode) for s in synth.values()])
    baselines.run(Baseline.GENPLAN, out / calibrate.REFERENCE, cfg, out / "genplan")
    for name in SUBSTITUTES:
        calibrate.write(out / name, names, calibrate.ROWS[name](sheets, rng))
    return [out / "genplan", out / "generator", *(out / n for n in SUBSTITUTES)]


def summary(out: Path, cfg: Config) -> str:
    """Сводка Markdown: строка таблицы на (строку, режим), реальные против реальных — последней
    в режиме; годных листов — из доли valid и числа домов."""
    columns = cfg.metrics.realtest.summary
    lines = ["| строка | режим | годных | " + " | ".join(columns) + " |",
             "|---|---|---|" + "---|" * len(columns)]
    for mode in Mode:
        rows = json.loads((out / mode / "rows" / table.METRICS).read_text())["rows"]
        half = json.loads((out / mode / "half" / table.METRICS).read_text())["rows"]
        named = [(Path(k).name, r) for k, r in rows.items()]
        named += [("real-half", r) for r in half.values()]
        lines += [f"| {name} | {mode} | {_good(r)} | " + " | ".join(str(r[c]) for c in columns)
                  + " |" for name, r in named]
    return "\n".join(lines) + "\n"


def _good(row: dict) -> str:
    n = row["count"]
    return f"{round((row['valid'] or 0) * n)}/{n}"


def _answers(given: dict[str, FacadeSheet], mode: Mode, cfg: Config, out: Path) -> Path:
    """Ответ модели на каждый дом: лист после шагов 4–5 или {"error": …} — брак после попыток."""
    out.mkdir(parents=True, exist_ok=True)
    for name, sheet in given.items():
        try:
            got = pipeline.layout(bare(sheet), pipeline.PlanRun(plan=name, text="", mode=mode), cfg)
            text = got.sheet.model_dump_json()
        except ModelError as e:
            text = json.dumps({"error": str(e)}, ensure_ascii=False)
        (out / f"{name}.json").write_text(text)
    return out
