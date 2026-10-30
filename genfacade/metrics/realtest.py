"""Таблица метрик против реального теста (gf#180, gf#210): эталон — дома ручной разметки, строки —
модель шага 4 (шаги 4–5 конвейера: страж, до attempts попыток; брак — {"error": …}), правило
GenPlan, синтетика val, подмены; калибровка «реальные против реальных» — половина домов против
другой. На машине с torch-fidelity в строках есть FID и KID (`genfacade realtest`, gpu.yml).

    <out>/<режим>/<строка>/<дом>.json   листы
    <out>/<режим>/rows/metrics.json     строки против всех реальных домов
    <out>/<режим>/half/metrics.json     половина реальных против другой
"""

import json
from pathlib import Path

import numpy

from genfacade import baselines, pipeline
from genfacade.baselines import Baseline
from genfacade.config import Config
from genfacade.metrics import calibrate, table
from genfacade.models.stub import ModelError
from genfacade.schema import FacadeSheet, Mode, Source, Split
from genfacade.train.tokens import bare, given_sides

HALVES = ("half-a", "half-b")
SUBSTITUTES = ("random", "foreign", "empty")
MODEL = "model"


def run(cfg: Config, out: Path, synthetic: int) -> Path:
    """Листы строк в каждом режиме и таблицы по ним; synthetic — домов синтетики val, 0 — все."""
    real = calibrate.houses(Source.MANUAL, Split.TEST, 0, cfg)
    synth = calibrate.houses(Source.SYNTHETIC, Split.VAL, synthetic, cfg)
    for mode in Mode:
        folders = _folders(real, synth, mode, cfg, out / mode)
        table.run(folders, out / mode / calibrate.REFERENCE, cfg, out / mode / "rows")
        table.run([out / mode / HALVES[0]], out / mode / HALVES[1], cfg, out / mode / "half")
    return out


def _folders(real: dict, synth: dict, mode: Mode, cfg: Config, out: Path) -> list[Path]:
    names, sheets = list(real), [given_sides(s, mode) for s in real.values()]
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
    rows = [out / "genplan", out / "generator", *(out / n for n in SUBSTITUTES)]
    if pipeline.trained_model(cfg.models.layout) is not None:
        _answers(names, sheets, mode, cfg, out / MODEL)
        rows.insert(0, out / MODEL)
    return rows


def _answers(names: list[str], sheets: list[FacadeSheet], mode: Mode, cfg: Config,
             out: Path) -> None:
    """Ответ модели на каждый дом: лист после шагов 4–5 или {"error": …} — брак после попыток."""
    out.mkdir(parents=True, exist_ok=True)
    for name, sheet in zip(names, sheets, strict=True):
        try:
            got = pipeline.layout(bare(sheet), pipeline.PlanRun(plan=name, text="", mode=mode), cfg)
            text = got.sheet.model_dump_json()
        except ModelError as e:
            text = json.dumps({"error": str(e)}, ensure_ascii=False)
        (out / f"{name}.json").write_text(text)
