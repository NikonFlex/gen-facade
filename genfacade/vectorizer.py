"""Базовый подход «растр + готовый векторизатор без структурных ограничений» (gf#17).

Верхняя граница векторизатора: растр не фото, а чистый рендер эталонной стены — плоские цвета
классов (`[vectorizer.colors]`, config/baselines.toml), ничего лишнего. Каждая стена реального
теста → растр → сторонний векторизатор (EvoVec из VGLib или vtracer, процесс отдельного venv,
`tools/vectorize_worker.py`) → цветные пути → осевая рамка каждого пути (мост методов из
`docs/methods.md`) → элемент того класса, чей цвет ближе: так готовый векторизатор отвечает на те
же дома, что модель, и идёт в таблицу `genfacade realtest` строкой `vectorizer-<имя>`.

    <out>/rasters/<номер>__<дом>__<стена>.npy   растры в порядке посева (PNG делает worker)
    <out>/traced/<номер>__<дом>__<стена>.json   ответ векторизатора на стену (`Traced`)
    <out>/<дом>.json                            элементы стен дома (`Extracted`), готовые дома
    <out>/damage.json                           что стало со структурой эталона (damage.py)

Прогон возобновляем: готовые ответы векторизатора не пересчитываются. Номер домов — перестановка
по `[metrics] seed`, чтобы недосчитанная выборка не состояла из одного источника разметки.
"""

import json
import subprocess  # noqa: S404 — запускаем свой worker с путями из конфига, без оболочки
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

import numpy
from PIL import Image

from genfacade import baselines, raster_panels, raster_read
from genfacade.config import Config
from genfacade.metrics import calibrate, damage, visual
from genfacade.schema import (
    Element,
    ElementClass,
    FacadeSheet,
    HouseSpec,
    Model,
    SideFacade,
    Source,
    Split,
)

RASTERS = "rasters"
TRACED = "traced"
SETTINGS = "settings.json"
SEP = "__"  # номер, дом и стена в имени растра
SKIPPED = frozenset({ElementClass.FACADE})  # стена — фон растра, не элемент


class Backend(StrEnum):
    EVOVEC = "evovec"
    VTRACER = "vtracer"
    REFERENCE = "reference"  # контроль без векторизатора: элементы эталона как есть


class Shape(Model):
    color: tuple[int, int, int]
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 в пикселях растра, y вниз
    segments: int


class Traced(Model):
    """Ответ векторизатора на одну стену."""

    seconds: float
    shapes: list[Shape]


class Extracted(Model):
    """Элементы стен одного дома из ответов векторизатора; seconds — время на весь дом."""

    seconds: float
    walls: list[list[Element]]


def houses(cfg: Config) -> dict[str, FacadeSheet]:
    """Дома реального теста — те же, что у строк `genfacade realtest`."""
    return calibrate.houses(Source.MANUAL, Split.TEST, 0, cfg)


def scale(f: SideFacade, spec: HouseSpec, cfg: Config) -> float:
    """Пикселей на метр: длинная сторона стены — `long_side_px`."""
    return cfg.baselines.vectorizer.long_side_px / max(f.side.length_m, spec.eaves_m)


def flat(f: SideFacade, spec: HouseSpec, cfg: Config) -> numpy.ndarray:
    """Растр стены H×W×3: элементы поверх стены плоскими цветами классов, холст — по стене."""
    settings = cfg.metrics.visual.model_copy(update={
        "px_per_m": scale(f, spec, cfg), "canvas_m": (f.side.length_m, spec.eaves_m),
        "colors": cfg.baselines.vectorizer.colors})
    return visual.mask(f, spec, settings)


def raster(f: SideFacade, spec: HouseSpec, cfg: Config) -> numpy.ndarray:
    """То, что получает векторизатор: плоский растр, при `[vectorizer.texture]` — с грязью."""
    return roughen(flat(f, spec, cfg), cfg)


def roughen(image: numpy.ndarray, cfg: Config) -> numpy.ndarray:
    """Полоски обшивки на цвете стены и шум по `[vectorizer.texture]`; нули — растр как есть."""
    texture = cfg.baselines.vectorizer.texture
    wall = (image == visual.rgb(cfg.baselines.vectorizer.colors[ElementClass.FACADE])).all(axis=2)
    out = image.astype(float)
    if texture.siding_px:
        lines = numpy.zeros(len(image), bool)
        lines[:: texture.siding_px] = True
        out[wall & lines[:, None]] *= 1 - texture.siding_dim
    if texture.noise:
        out += numpy.random.default_rng(cfg.metrics.seed).normal(0, texture.noise, out.shape)
    return numpy.clip(out.round(), 0, 255).astype(numpy.uint8)


def order(names: list[str], cfg: Config) -> list[str]:
    """Порядок домов прогона — перестановка по seed метрик."""
    return [names[k] for k in numpy.random.default_rng(cfg.metrics.seed).permutation(len(names))]


def write_rasters(real: dict[str, FacadeSheet], cfg: Config, out: Path, limit: int) -> int:
    """Растры стен первых `limit` домов порядка (0 — всех); число стен."""
    (out / RASTERS).mkdir(parents=True, exist_ok=True)
    walls = 0
    for rank, name in enumerate(order(list(real), cfg)[: limit or None]):
        sheet = real[name]
        for k, f in enumerate(sheet.facades):
            file = out / RASTERS / f"{rank:03d}{SEP}{name}{SEP}{k}.npy"
            numpy.save(file, raster(f, sheet.spec, cfg))
            walls += 1
    return walls


def settings(backend: Backend, cfg: Config, out: Path) -> Path:
    """Настройки процесса векторизатора — файлом: у него свой интерпретатор и свой код."""
    run = cfg.baselines.vectorizer
    evovec = {**run.evovec.model_dump(), "code": str(run.evovec.code.resolve())}
    data = {"backend": backend, "work": str((out / "work").resolve()), "evovec": evovec,
            "vtracer": run.vtracer.model_dump()}
    path = out / SETTINGS
    path.write_text(json.dumps(data, indent=1))
    return path


def trace(backend: Backend, cfg: Config, out: Path) -> None:
    """Все растры папки — векторизатору, в `jobs` процессов; упал процесс — отказ."""
    run = cfg.baselines.vectorizer
    (out / TRACED).mkdir(exist_ok=True)
    logs = []
    for k in range(run.jobs):
        log = (out / f"log-{k}.txt").open("w")
        command = [str(run.python), str(run.worker), str(settings(backend, cfg, out)),
                   str(out / RASTERS), str(out / TRACED), str(k), str(run.jobs)]
        logs.append((subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT), log))  # noqa: S603
    for process, log in logs:
        process.wait()
        log.close()
    if failed := [p.returncode for p, _ in logs if p.returncode]:
        raise RuntimeError(f"векторизатор упал, коды {failed}: см. {out}/log-*.txt")


def nearest(color: tuple[int, int, int], cfg: Config) -> ElementClass:
    """Класс, чей цвет на растре ближе к цвету пути."""
    palette = {cls: visual.rgb(c) for cls, c in cfg.baselines.vectorizer.colors.items()}
    return min(palette, key=lambda cls: sum((a - b) ** 2 for a, b in zip(color, palette[cls],
                                                                          strict=True)))


def place(box: tuple[float, float, float, float], ppm: float, spec: HouseSpec) -> dict:
    """Рамка в пикселях растра (y вниз) → поля `Element`: метры от левого низа стены и этаж."""
    x0, y0, x1, y1 = box
    y_m = (round(spec.eaves_m * ppm) - y1) / ppm
    floor = sum(level <= y_m + (y1 - y0) / ppm / 2 for level in spec.floor_levels()[:-1])
    return {"x_m": x0 / ppm, "y_m": y_m, "w_m": (x1 - x0) / ppm, "h_m": (y1 - y0) / ppm,
            "floor": max(floor, 1)}


def crumb(box: tuple[float, float, float, float], cfg: Config) -> bool:
    """Крошка трассировки: рамка уже `min_side_px` — не элемент."""
    x0, y0, x1, y1 = box
    return min(x1 - x0, y1 - y0) < cfg.baselines.vectorizer.min_side_px


def elements(traced: Traced, f: SideFacade, spec: HouseSpec, cfg: Config) -> list[Element]:
    """Пути стены → элементы по рамке пути, класс — по цвету заливки. Это чтение «путь = элемент»:
    меряет устройство SVG (склейки, закрытые пути), а не картинку; элементы картинки — `visible`."""
    ppm, out = scale(f, spec, cfg), []
    for k, shape in enumerate(traced.shapes):
        cls = nearest(shape.color, cfg)
        if cls not in SKIPPED and not crumb(shape.box, cfg):
            out.append(Element(id=f"v{k + 1}", cls=cls, **place(shape.box, ppm, spec)))
    return out


def load(picture: Path) -> numpy.ndarray:
    """Отрисовка SVG векторизатора: H×W×3."""
    with Image.open(picture) as image:
        return numpy.asarray(image.convert("RGB"))


def visible(picture: Path, f: SideFacade, spec: HouseSpec, cfg: Config) -> list[Element]:
    """Элементы стены с отрисовки SVG: связные области цвета класса (раздел `raster_read`); крошка
    не элемент. Склеенный путь даёт столько элементов, сколько кусков на картинке."""
    ppm, out = scale(f, spec, cfg), []
    for k, region in enumerate(raster_read.regions(
            raster_read.classes(load(picture), cfg), cfg)):
        if not crumb(region.box, cfg):
            out.append(Element(id=f"r{k + 1}", cls=region.cls, **place(region.box, ppm, spec)))
    return out


def seen(f: SideFacade, spec: HouseSpec, cfg: Config) -> list[Element]:
    """Проёмы эталонной стены, которые видны на растре: рамка — в пределах стены до карниза, а
    цвет класса занимает не меньше `min_visible` рамки — иначе элемент закрыт поверх нарисованным
    (навес на окне) или срезан карнизом, и «потерей векторизатора» его считать нельзя."""
    run, image, ppm = cfg.baselines.vectorizer, flat(f, spec, cfg), scale(f, spec, cfg)
    out = []
    for e in damage.elements_of(f):
        x0, y0 = max(e.x_m, 0.0), max(e.y_m, 0.0)
        x1, y1 = min(e.x_m + e.w_m, f.side.length_m), min(e.y_m + e.h_m, spec.eaves_m)
        if x1 <= x0 or y1 <= y0:
            continue
        rows = slice(image.shape[0] - round(y1 * ppm), image.shape[0] - round(y0 * ppm))
        patch = image[rows, round(x0 * ppm):round(x1 * ppm)]
        if (patch == visual.rgb(run.colors[e.cls])).all(axis=2).mean() >= run.min_visible:
            out.append(e.model_copy(update={"x_m": x0, "y_m": y0, "w_m": x1 - x0, "h_m": y1 - y0}))
    return out


class Answer(NamedTuple):
    """Ответ векторизатора на стену: пути из SVG и то, что получилось на его отрисовке."""

    traced: Traced
    picture: Path


def _answers(folder: Path) -> dict[str, dict[int, Answer]]:
    """Ответы векторизатора по домам и стенам; отрисовка `.png` лежит рядом с `.json`."""
    out: dict[str, dict[int, Answer]] = {}
    for path in sorted(folder.glob("*.json")):
        _, name, wall = path.stem.split(SEP)
        traced = Traced.model_validate_json(path.read_text())
        out.setdefault(name, {})[int(wall)] = Answer(traced, path.with_suffix(".png"))
    return out


def collect(real: dict[str, FacadeSheet], cfg: Config, out: Path) -> list[str]:
    """Дома, у которых ответ есть на каждую стену, → `<дом>.json` (элементы с отрисовки) и
    `damage.json` (видимое — на верхнем уровне, устройство SVG — в `svg_paths`)."""
    answers, done = _answers(out / TRACED), {}
    for name, sheet in real.items():
        got = answers.get(name, {})
        if len(got) != len(sheet.facades):
            continue
        walls = [visible(got[k].picture, f, sheet.spec, cfg) for k, f in enumerate(sheet.facades)]
        seconds = round(sum(a.traced.seconds for a in got.values()), 1)
        done[name] = Extracted(seconds=seconds, walls=walls)
        (out / f"{name}.json").write_text(done[name].model_dump_json())
    (out / "damage.json").write_text(json.dumps(summary(real, answers, done, cfg), indent=1))
    return list(done)


def summary(real: dict[str, FacadeSheet], answers: dict[str, dict[int, Answer]],
            done: dict[str, Extracted], cfg: Config) -> dict:
    """`damage.json`: что стало со структурой эталона на картинке и отдельно — каков SVG."""
    reference = {n: [seen(f, real[n].spec, cfg) for f in real[n].facades] for n in done}
    report = damage.report(real, reference, {n: e.walls for n, e in done.items()}, cfg)
    everything = sum(len(damage.elements_of(f)) for n in done for f in real[n].facades)
    report["hidden"] = everything - sum(len(w) for walls in reference.values() for w in walls)
    report["walls"] = sum(len(e.walls) for e in done.values())
    return {**report, "svg_paths": svg_paths(real, answers, reference, cfg)}


def svg_paths(real: dict[str, FacadeSheet], answers: dict[str, dict[int, Answer]],
              reference: dict[str, list[list[Element]]], cfg: Config) -> dict:
    """Мера «SVG — чертёж с объектами», не мера картинки: тот же `damage.report`, но элемент —
    рамка пути SVG; сколько путей на стене и сколько из них закрыты (цвет пути почти не виден
    на отрисовке в его рамке, `hidden_path_share`)."""
    by_path = {n: [elements(answers[n][k].traced, f, real[n].spec, cfg)
                   for k, f in enumerate(real[n].facades)] for n in reference}
    shapes = [a for n in reference for a in answers[n].values()]
    hidden = sum(hidden_paths(a, cfg) for a in shapes)
    paths = sum(len(a.traced.shapes) for a in shapes)
    return {"walls": len(shapes), "paths": paths, "paths_hidden": hidden,
            "report": damage.report(real, reference, by_path, cfg)}


def hidden_paths(answer: Answer, cfg: Config) -> int:
    """Путей стены, закрытых на отрисовке: цвет пути занимает меньше `hidden_path_share` рамки."""
    index, order = raster_read.classes(load(answer.picture), cfg), raster_read.palette(cfg)
    limit, count = cfg.baselines.vectorizer.hidden_path_share, 0
    for shape in answer.traced.shapes:
        box = tuple(round(v) for v in shape.box)
        cls = order.index(nearest(shape.color, cfg))
        count += raster_read.visible_share(index, box, cls) < limit
    return count


def panels(out: Path, stems: list[str], cfg: Config) -> list[Path]:
    """Картинки стен `stems` (имя растра без расширения) → `<out>/panels/<стена>.png`."""
    (out / "panels").mkdir(exist_ok=True)
    files = []
    for stem in stems:
        rendered = load(out / TRACED / f"{stem}.png")
        found = raster_read.regions(raster_read.classes(rendered, cfg), cfg)
        picture = raster_panels.draw(numpy.load(out / RASTERS / f"{stem}.npy"), rendered,
                                     [r for r in found if not crumb(r.box, cfg)])
        files.append(out / "panels" / f"{stem}.png")
        picture.save(files[-1])
    return files


def run(backend: Backend, cfg: Config, out: Path, limit: int) -> Path:
    """Растры → векторизатор → элементы домов; `limit` домов порядка, 0 — все."""
    real = houses(cfg)
    out.mkdir(parents=True, exist_ok=True)
    if backend is Backend.REFERENCE:
        return control(real, out)
    write_rasters(real, cfg, out, limit)
    trace(backend, cfg, out)
    collect(real, cfg, out)
    return out


def control(real: dict[str, FacadeSheet], out: Path) -> Path:
    """Строка-контроль: стены с элементами эталона и одной отделкой, как у векторизатора. От неё
    до эталона — вклад упрощённой стены (нет зон, цоколя, пояса), а не векторизатора."""
    for name, sheet in real.items():
        walls = [f.elements for f in sheet.facades]
        (out / f"{name}.json").write_text(Extracted(seconds=0.0, walls=walls).model_dump_json())
    return out


def sheet(given: FacadeSheet, extracted: Extracted) -> FacadeSheet:
    """Лист дома со стенами из ответа векторизатора: стороны и параметры — реального дома с
    условием режима, элементы — векторизатора, стена — одной отделкой (как у правила GenPlan)."""
    facades = [f.model_copy(update={"elements": els, "zones": [baselines.main_zone(f, given)]})
               for f, els in zip(given.facades, extracted.walls, strict=True)]
    return given.model_copy(update={"facades": facades})


def write_row(given: dict[str, FacadeSheet], source: Path, out: Path) -> Path:
    """Строка таблицы: листы домов, которые векторизатор успел (папка `source` от `run`)."""
    done = {n: Extracted.model_validate_json((source / f"{n}.json").read_text())
            for n in given if (source / f"{n}.json").exists()}
    calibrate.write(out, list(done), [sheet(given[n], e) for n, e in done.items()])
    return out
