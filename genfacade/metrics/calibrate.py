"""Калибровка метрик с двух концов (gf#16): эталон генератора обязан выигрывать у подмен.

Эталонное распределение — дома train, строки — дома val в каждом режиме:
- generator — ответ генератора синтетики (сам эталон, на других домах);
- random    — те же окна тех же размеров, расставленные по стене случайно;
- foreign   — элементы и зоны чужого дома: настоящая раскладка не к этим стенам;
- constant  — на всех стенах одна и та же раскладка;
- empty     — элементов нет, зоны на месте.
Если метрика не отличает эталон от подмены, которая бьёт в её группу, она ничего не мерит.

    <out>/<режим>/reference/<дом>.json   — эталонное распределение (train)
    <out>/<режим>/<строка>/<дом>.json    — строки таблицы (val)
"""

from collections.abc import Callable
from pathlib import Path

import numpy

from genfacade.config import Config
from genfacade.datasets import store
from genfacade.metrics import measures, table
from genfacade.schema import FacadeSheet, Mode, SideFacade, Source, Split
from genfacade.train.tokens import given_sides

REFERENCE = "reference"
Substitute = Callable[[list[FacadeSheet], numpy.random.Generator], list[FacadeSheet]]


def _walls(sheet: FacadeSheet, walls: list[SideFacade]) -> FacadeSheet:
    return sheet.model_copy(update={"facades": walls})


def _with(f: SideFacade, elements: list, zones: list) -> SideFacade:
    return f.model_copy(update={"elements": elements, "zones": zones})


def generator(sheets: list[FacadeSheet], rng: numpy.random.Generator) -> list[FacadeSheet]:
    return sheets


def random(sheets: list[FacadeSheet], rng: numpy.random.Generator) -> list[FacadeSheet]:
    """Окна те же по числу и размеру, место — случайное в пределах стены; их подоконники и
    наличники убраны, двери и карниз остаются."""
    return [_walls(s, [_scatter(f, s, rng) for f in s.facades]) for s in sheets]


def _scatter(f: SideFacade, s: FacadeSheet, rng: numpy.random.Generator) -> SideFacade:
    ws = {w.id for w in measures.windows(f)}
    kept = [e for e in f.elements if e.id not in ws and e.parent not in ws]
    moved = [w.model_copy(update={
        "x_m": float(rng.uniform(0, max(f.side.length_m - w.w_m, 0))),
        "y_m": float(rng.uniform(s.spec.plinth_m, max(s.spec.eaves_m - w.h_m, s.spec.plinth_m))),
        "fixed": []}) for w in measures.windows(f)]
    moved = [w.model_copy(update={"floor": min(measures.floor_of(w, s.spec), s.spec.floors)})
             for w in moved]
    return _with(f, kept + moved, f.zones)


def foreign(sheets: list[FacadeSheet], rng: numpy.random.Generator) -> list[FacadeSheet]:
    """Раскладка следующего дома по кругу, стена к стене."""
    out = []
    for s, other in zip(sheets, sheets[1:] + sheets[:1], strict=True):
        theirs = other.facades
        out.append(_walls(s, [_with(f, theirs[k % len(theirs)].elements,
                                    theirs[k % len(theirs)].zones)
                              for k, f in enumerate(s.facades)]))
    return out


def constant(sheets: list[FacadeSheet], rng: numpy.random.Generator) -> list[FacadeSheet]:
    """Раскладка первой стены с окнами — на всех стенах всех домов."""
    model = next(f for s in sheets for f in s.facades if measures.windows(f))
    return [_walls(s, [_with(f, model.elements, model.zones) for f in s.facades])
            for s in sheets]


def empty(sheets: list[FacadeSheet], rng: numpy.random.Generator) -> list[FacadeSheet]:
    return [_walls(s, [_with(f, [], f.zones) for f in s.facades]) for s in sheets]


ROWS: dict[str, Substitute] = {"generator": generator, "random": random, "foreign": foreign,
                               "constant": constant, "empty": empty}


def houses(source: Source, split: Split, count: int, cfg: Config) -> dict[str, FacadeSheet]:
    """Первые count домов части (0 — все): имя → лист."""
    root, out = cfg.data.paths.samples_dir, {}
    for name in store.ids(root, source):
        sample = store.read(root, source, name)
        if sample.split is split:
            out[name] = sample.sheet
            if count and len(out) >= count:
                break
    return out


def write(folder: Path, names: list[str], sheets: list[FacadeSheet]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, sheet in zip(names, sheets, strict=True):
        (folder / f"{name}.json").write_text(sheet.model_dump_json())


def run(source: Source, cfg: Config, out: Path) -> Path:
    """Папки эталона и подмен в каждом режиме и таблица метрик по ним."""
    ref = houses(source, Split.TRAIN, cfg.metrics.calibrate.reference, cfg)
    val = houses(source, Split.VAL, 0, cfg)
    folders = []
    for mode in Mode:
        write(out / mode / REFERENCE, list(ref), [given_sides(s, mode) for s in ref.values()])
        sheets = [given_sides(s, mode) for s in val.values()]
        for name, substitute in ROWS.items():
            rng = numpy.random.default_rng(cfg.metrics.seed)
            write(out / mode / name, list(val), substitute(sheets, rng))
            folders.append(out / mode / name)
    return _tables(folders, out, cfg)


def _tables(folders: list[Path], out: Path, cfg: Config) -> Path:
    """Таблица на режим: у каждого режима свой эталон."""
    for mode in Mode:
        rows = [f for f in folders if f.parent.name == mode]
        table.run(rows, out / mode / REFERENCE, cfg, out / mode)
    return out

