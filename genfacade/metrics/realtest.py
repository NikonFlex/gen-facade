"""Таблица метрик против реального теста (gf#180, gf#210): эталон — дома ручной разметки, строки —
модель шага 4 (шаги 4–5 конвейера: страж, до attempts попыток; брак — {"error": …}), правило
GenPlan, синтетика val, подмены; калибровка «реальные против реальных» — половина домов против
другой. На машине с torch-fidelity в строках есть FID и KID (`genfacade realtest`, gpu.yml).

    <out>/<режим>/<строка>/<дом>.json   листы
    <out>/<режим>/rows/metrics.json     строки против всех реальных домов
    <out>/<режим>/half/metrics.json     подмены из одной половины реальных и сама она — против
                                        другой половины
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
from genfacade.schema import FacadeSheet, Mode, Refusal, Source, Split
from genfacade.train import tokens
from genfacade.train.tokens import bare, given_sides

HALVES = ("half-a", "half-b")
REFUSED = "refusal"  # ключ ответа-отказа модели в <дом>.json строки модели: Refused.record()
SUBSTITUTES = ("random", "foreign", "empty")
MODEL = "model"
SUMMARY = "summary.md"
REAL_HALF = "real-half"
GOOD = "годных"    # колонка: листов с разобранным SVG из всех домов, «k/n»


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
        folders, substitutes = _folders(given, synth, mode, cfg, out / mode)
        table.run(models + folders, out / mode / calibrate.REFERENCE, cfg, out / mode / "rows")
        table.run([*substitutes, out / mode / HALVES[0]], out / mode / HALVES[1], cfg,
                  out / mode / "half")
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
            raise ModelError(Refusal.MODEL_MISSING, f"нет чекпойнта {path}")
        if model.words != tokens.vocabulary(cfg):
            raise ModelError(Refusal.MODEL_MISMATCH,
                             f"словарь {path} не совпадает с нынешней записью токенов: листы "
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


def _folders(given: dict, synth: dict, mode: Mode, cfg: Config,
             out: Path) -> tuple[list[Path], list[Path]]:
    """Эталон, половины, синтетика, правило GenPlan и подмены — строки без модели; given —
    реальные дома с условием режима. Вернуть строки против всех реальных домов и подмены —
    они из первой половины домов и идут против второй, как «реальные против реальных»: подмена
    копирует у настоящего дома всё, кроме места окон, и против своих же домов находила у каждой
    стены близнеца (c2st random по доле остекления 0,082, gf#268)."""
    names, sheets = list(given), list(given.values())
    rng = numpy.random.default_rng(cfg.metrics.seed)
    calibrate.write(out / calibrate.REFERENCE, names, sheets)
    first = set(rng.permutation(names)[: len(names) // 2])
    halves = []
    for part, keep in zip(HALVES, (True, False), strict=True):
        pick = [(n, s) for n, s in zip(names, sheets, strict=True) if (n in first) == keep]
        calibrate.write(out / part, [n for n, _ in pick], [s for _, s in pick])
        halves.append(pick)
    calibrate.write(out / "generator", list(synth), [given_sides(s, mode) for s in synth.values()])
    baselines.run(Baseline.GENPLAN, out / calibrate.REFERENCE, cfg, out / "genplan")
    own = [n for n, _ in halves[0]]
    for name in SUBSTITUTES:
        calibrate.write(out / name, own, calibrate.ROWS[name]([s for _, s in halves[0]], rng))
    return [out / "genplan", out / "generator"], [out / n for n in SUBSTITUTES]


def named_rows(out: Path, mode: Mode) -> list[tuple[str, dict]]:
    """Строки таблицы режима из metrics.json (а не из summary.md): (имя строки, её метрики);
    подмены и реальные против реальных — из таблицы половин, реальные — последней, под именем
    real-half."""
    def read(part: str) -> list[tuple[str, dict]]:
        rows = json.loads((out / mode / part / table.METRICS).read_text())["rows"]
        return [(Path(k).name, r) for k, r in rows.items()]

    half = [(REAL_HALF if n == HALVES[0] else n, r) for n, r in read("half")]
    return read("rows") + half


def summary(out: Path, cfg: Config) -> str:
    """Сводка Markdown: строка таблицы на (строку, режим), реальные против реальных — последней
    в режиме; годных листов — из доли valid и числа домов."""
    columns = cfg.metrics.realtest.summary
    lines = [f"| строка | режим | {GOOD} | " + " | ".join(columns) + " |",
             "|---|---|---|" + "---|" * len(columns)]
    for mode in Mode:
        lines += [f"| {name} | {mode} | {good(r)} | " + " | ".join(str(r[c]) for c in columns)
                  + " |" for name, r in named_rows(out, mode)]
    return "\n".join(lines) + "\n"


def good_count(row: dict) -> int:
    return round((row["valid"] or 0) * row["count"])


def good(row: dict) -> str:
    return f"{good_count(row)}/{row['count']}"


def _answers(given: dict[str, FacadeSheet], mode: Mode, cfg: Config, out: Path) -> Path:
    """Ответ модели на каждый дом: лист после шагов 4–5 или {"refusal": …, "attempts": …} — брак
    после попыток; у неразобранной попытки — её слова (датчик обрыва gf#257)."""
    out.mkdir(parents=True, exist_ok=True)
    for name, sheet in given.items():
        try:
            got = pipeline.layout(bare(sheet), pipeline.PlanRun(plan=name, text="", mode=mode), cfg)
            text = got.sheet.model_dump_json()
        except ModelError as e:
            text = json.dumps({REFUSED: e.record(), "attempts": e.attempts}, ensure_ascii=False)
        (out / f"{name}.json").write_text(text)
    return out
