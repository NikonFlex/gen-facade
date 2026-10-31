"""Конвейер и его трасса: выход каждого шага — в папку прогона
(`generation: Конвейер из семи шагов`, `generation: Трасса шагов`).

`generate`: SVG-план GenPlan + текст → шаги 1–6, у каждого JSON и SVG. Смотрелка и CLI читают
одно и то же — папку прогона с `meta.json`, где перечислены шаги и файлы. Прогон, остановленный
отказом (план отклонён, модель не ответила), тоже пишет `meta.json`: шаги до отказа и причину.
"""

import json
import math
import re
import subprocess  # noqa: S404 — только git rev-parse
from collections.abc import Iterator
from datetime import datetime
from importlib.metadata import version
from itertools import islice
from pathlib import Path
from typing import NamedTuple

import numpy
from pydantic import BaseModel

from genfacade.config import Config, LayoutModel
from genfacade.metrics import realism
from genfacade.models import stub
from genfacade.models.stub import ModelError
from genfacade.plan.genplan_svg import PlanError
from genfacade.plan.preprocess import preprocess
from genfacade.render.plan_svg import plan_svg
from genfacade.render.preview import to_png
from genfacade.render.spec_svg import spec_svg
from genfacade.render.svg import sheet_svg
from genfacade.schema import FacadeSheet, HouseSpec, Mode, Plan, Rule, SideFacade, Violation
from genfacade.snap import snap
from genfacade.train.tokens import TokenError
from genfacade.unfold import unfold
from genfacade.validate import errors, validate

SPEC, PLAN_SVG, UNFOLD, LAYOUT, SNAPPED, SHEET = (
    "01_spec.json", "02_plan.svg", "03_unfold.svg", "04_layout.svg", "05_snapped.svg",
    "06_sheet.svg")
SPEC_SVG, PLAN_JSON, UNFOLD_JSON, LAYOUT_JSON, SNAPPED_JSON, SHEET_JSON = (
    "01_spec.svg", "02_plan.json", "03_unfold.json", "04_layout.json", "05_snapped.json",
    "sheet.json")
REQUEST, INPUT_PLAN, VIOLATIONS, PREVIEW, META = (
    "request.json", "input_plan.svg", "violations.json", "preview.png", "meta.json")


class Step(NamedTuple):
    """Шаг схемы в трассе: поля — как в meta.json, их читает смотрелка; файла, которого
    прогон не написал (остановлен отказом раньше), в meta.json нет — там None."""

    n: int
    title: str
    file: str | None  # что шаг показывает в смотрелке
    json: str | None = None  # выход шага (`generation: Трасса шагов`): JSON…
    svg: str | None = None   # …и SVG


FILE_FIELDS = ("file", "json", "svg")  # поля Step с именами файлов

# Семь шагов схемы (docs/assets/facade-modules.png); седьмой — позже, вместе с Егором.
STEPS = (
    Step(1, "Параметры дома", SPEC, SPEC, SPEC_SVG),
    Step(2, "План", PLAN_SVG, PLAN_JSON, PLAN_SVG),
    Step(3, "Развёртка", UNFOLD, UNFOLD_JSON, UNFOLD),
    Step(4, "Раскладка стен", LAYOUT, LAYOUT_JSON, LAYOUT),
    Step(5, "Сетка и проверка", SNAPPED, SNAPPED_JSON, SNAPPED),
    Step(6, "Лист фасадов", SHEET, SHEET_JSON, SHEET),
)
# Отказ прогона → с чего начинается его причина: в CLI, в смотрелке и в meta.json одинаково.
REFUSALS = {PlanError: "план отклонён", ModelError: "модель не ответила"}
RUN_ID = re.compile(r"^[\w.-]+$")  # имя папки прогона: без / и .., чтобы не выйти из runs_dir


class PlanRun(BaseModel):
    """Запрос на прогон (спека task, «Запрос»): план — имя или путь, откуда он пришёл.

    seed запроса нет: попытки модели идут с seed из config/models.toml, какой сработал —
    в meta.json («layout»).
    """

    plan: str
    text: str
    mode: Mode = Mode.WITH_OPENINGS


def new_run_dir(runs_dir: Path, name: str) -> Path:
    """Свободная папка <время>-<имя>; два запуска в одну секунду получают суффикс."""
    base = f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^\w.-]', '_', name)}"
    out, n = runs_dir / base, 2
    while out.exists():
        out, n = runs_dir / f"{base}-{n}", n + 1
    return out


def generate(req: PlanRun, svg: str, out: Path, cfg: Config) -> Path:
    """План GenPlan + текст → трасса шагов 1–6.

    Дефектный план — PlanError, вход, на который не ответит модель (стаб), — ModelError; трасса
    до отказа и meta.json с причиной («refusal») остаются в папке прогона.
    """
    out.mkdir(parents=True, exist_ok=True)
    for name in _trace_files():  # папка задана руками (-o): шаги прошлого прогона — не наши
        (out / name).unlink(missing_ok=True)
    (out / INPUT_PLAN).write_text(svg)
    (out / REQUEST).write_text(req.model_dump_json(indent=2))
    base = {"source": req.plan, "input": REQUEST, "plan_input": INPUT_PLAN,
            "request": req.model_dump()}
    try:
        raw, sheet, violations, trace = layout(_prepare(req, svg, out, cfg), req, cfg)
    except tuple(REFUSALS) as e:
        write_meta(out, cfg, {**base, "refusal": f"{REFUSALS[type(e)]}: {e}"})
        raise
    _write(out, 4, raw, sheet_svg(raw, cfg, violations=[], annotations=False))
    _write(out, 5, sheet, sheet_svg(sheet, cfg, violations=violations, annotations=False))
    (out / VIOLATIONS).write_text(json.dumps(
        [v.model_dump() for v in violations], ensure_ascii=False, indent=2))
    extra = {
        **base, "violations": VIOLATIONS, "layout": trace,
        "errors": len(errors(violations)), "warnings": len(violations) - len(errors(violations)),
    }
    return finish(sheet, out, cfg, extra)


def _trace_files() -> set[str]:
    """Все файлы, которые пишет прогон, кроме входа."""
    steps = {getattr(s, k) for s in STEPS for k in FILE_FIELDS}
    return steps | {VIOLATIONS, PREVIEW, META}


def _write(out: Path, n: int, model: BaseModel, svg: str) -> None:
    """Выход шага n: JSON и SVG (`generation: Трасса шагов`)."""
    step = STEPS[n - 1]
    (out / step.json).write_text(model.model_dump_json(indent=2))
    (out / step.svg).write_text(svg)


class Checked(NamedTuple):
    """Шаги 4–5: ответ модели, он же после привязки, нарушения и как он получен (в meta.json)."""

    raw: FacadeSheet
    sheet: FacadeSheet
    violations: list[Violation]
    layout: dict


def layout(bare: FacadeSheet, req: PlanRun, cfg: Config) -> Checked:
    """Шаги 4–5. Обученная модель (config/models.toml), если чекпойнт есть, иначе стаб.
    Брак модели — ответ не разобран или ошибка валидатора — генерация заново с новым seed
    (`generation: Брак — заново`), с `wall_retry` — только бракованной стены; из best_of годных
    ответов берётся самый правдоподобный (gf#213). Стаб детерминирован, его не повторяем."""
    settings = cfg.models.layout
    model = trained_model(settings)
    if model is None:
        raw = stub.layout_all(bare, stub.LayoutContext(bare.spec, req.mode, req.text))
        return _check(raw, cfg, {"model": "stub", "attempts": []})
    trace = {"model": str(settings.checkpoint), "attempts": []}
    good = list(islice(_good(model, model.prompt(bare, req.mode, cfg), bare, cfg, trace),
                       settings.best_of))
    if not good:
        raise ModelError(f"за {len(trace['attempts'])} попыток нет годного ответа; последняя "
                         f"причина — {trace['attempts'][-1]['error']}")
    return good[0] if len(good) == 1 else _likeliest(good, Path(req.plan).stem, cfg)


def _good(model, prompt, bare: FacadeSheet, cfg: Config, trace: dict) -> Iterator[Checked]:
    """Годные ответы модели по очереди, до attempts раундов. Раунд k — seed + k: бракованные
    стены прошлого раунда досэмплируются (`wall_retry`), недостающие до best_of ответы — одной
    пачкой (`Layout.answers`). При best_of = 1 раунд — одна попытка, как до gf#213."""
    settings, redo, found = cfg.models.layout, [], 0
    for seed in range(settings.seed, settings.seed + settings.attempts):
        got = [(_redone(model, prompt, bare, old, wall, seed, cfg), wall) for old, wall in redo]
        need = settings.best_of - found - len(redo)
        fresh = model.answers(prompt, bare, seed, cfg, need) if need > 0 else []
        redo = []
        for answer, wall in got + [(a, None) for a in fresh]:
            result, bad = _attempt(answer, {"seed": seed, "wall": wall}, cfg, trace)
            if result is not None and not bad:
                found += 1
                yield result
            elif bad and settings.wall_retry and (at := _bad_wall(bad, answer.sheet)) is not None:
                redo.append((answer, at))


def _redone(model, prompt, bare: FacadeSheet, old, wall: int, seed: int, cfg: Config):
    try:
        return model.redo(prompt, bare, old, wall, seed, cfg)
    except TokenError as e:
        return e


def _attempt(answer, attempt: dict, cfg: Config,
             trace: dict) -> tuple[Checked | None, list[Violation]]:
    """Попытка в трассу: ответ не разобран (TokenError) или ошибки валидатора — причина."""
    if attempt["wall"] is None:
        del attempt["wall"]
    trace["attempts"].append(attempt)
    if isinstance(answer, TokenError):
        attempt["error"] = f"ответ не разобран: {answer}"
        return None, []
    result = _check(answer.sheet, cfg, trace)
    bad = errors(result.violations)
    attempt["error"] = _rejected(bad) if bad else None
    return result, bad


def _bad_wall(bad: list[Violation], sheet: FacadeSheet) -> int | None:
    """Номер стены в ответе (порядок `sheet.facades`), на которой первая ошибка; ошибка не
    на стене (угол) — None: досэмплировать надо весь дом."""
    sides = [v.side for v in bad]
    if None in sides or any(v.rule is Rule.CORNER for v in bad):
        return None
    order = [f.side.index for f in sheet.facades]
    return min(order.index(s) for s in sides)


def _likeliest(good: list[Checked], name: str, cfg: Config) -> Checked:
    """Годный ответ с наибольшей density стен против домов эталона, кроме дома name
    (`metrics.realism.house_density`, gf#210). Эталона нет — первый годный."""
    ref, settings = _reference(cfg, name), cfg.metrics.realism
    scores = [realism.house_density(realism.walls([g.sheet], settings), ref, settings.k)
              if len(ref) else None for g in good]
    best = max(range(len(good)), key=lambda i: -math.inf if scores[i] is None else scores[i])
    good[best].layout["density"] = scores
    good[best].layout["chosen"] = best
    return good[best]


_houses: dict[tuple, dict[str, numpy.ndarray]] = {}


def _reference(cfg: Config, without: str) -> numpy.ndarray:
    """Стены домов [layout.reference], кроме дома without; дома читаются раз на процесс."""
    from genfacade.metrics import calibrate  # он через store импортирует этот модуль

    ref = cfg.models.layout.reference
    key = (cfg.data.paths.samples_dir.resolve(), ref.source, ref.split)
    if key not in _houses:
        houses = calibrate.houses(ref.source, ref.split, 0, cfg)
        _houses[key] = {n: realism.walls([s], cfg.metrics.realism) for n, s in houses.items()}
    rest = [w for n, w in _houses[key].items() if n != without and len(w)]
    return numpy.vstack(rest) if rest else numpy.empty((0, 0))


def trained_model(settings: LayoutModel):
    """Обученная модель шага 4 или None, если чекпойнта нет. Тесты подменяют эту функцию:
    конвейер не зависит от файлов на диске."""
    if not settings.checkpoint.is_file():
        return None
    # torch — в группе [train]: без обученной модели конвейер его не тянет.
    from genfacade.models import layout

    return layout.load(settings)


def _check(raw: FacadeSheet, cfg: Config, trace: dict) -> Checked:
    sheet = snap(raw, cfg.checks)
    return Checked(raw, sheet, validate(sheet, cfg.checks), trace)


def _rejected(bad: list[Violation]) -> str:
    return f"ошибок валидатора {len(bad)}, первая — {bad[0].rule}: {bad[0].message}"


def walls(spec: HouseSpec, plan: Plan) -> FacadeSheet:
    """Шаг 3: пустые прямоугольники стен всех сторон плана, без крыши."""
    return unfold(FacadeSheet(spec=spec, facades=[SideFacade(side=s) for s in plan.sides]))


def _prepare(req: PlanRun, svg: str, out: Path, cfg: Config) -> FacadeSheet:
    """Шаги 1–3: параметры дома, план, развёртка — с трассой.

    Шаг 1 — модель (пока стаб): текст → HouseSpec.
    """
    spec = stub.spec_model(req.text, cfg.models.spec)
    # цвета — для смотрелки: у палитры без цвета берётся цвет вида из библиотеки
    colors = {m.id: m.color or cfg.library.kinds.get(m.kind) for m in spec.materials}
    (out / SPEC).write_text(json.dumps({"spec": spec.model_dump(), "colors": colors},
                                       ensure_ascii=False, indent=2))
    (out / SPEC_SVG).write_text(spec_svg(spec, cfg))
    plan = preprocess(svg, req.mode, cfg.plan)
    _write(out, 2, plan, plan_svg(plan, cfg))
    bare = walls(spec, plan)
    _write(out, 3, bare, sheet_svg(bare, cfg, annotations=False))
    return bare


def finish(sheet: FacadeSheet, out: Path, cfg: Config, extra: dict) -> Path:
    """Шаг 6 и meta.json: лист, JSON, PNG; extra — поля прогона, они же заменяют общие
    (у просмотра примера датасета шагов меньше — datasets/preview.py)."""
    (out / SHEET).write_text(sheet_svg(sheet, cfg))
    (out / SHEET_JSON).write_text(sheet.model_dump_json(indent=2))
    has_png = to_png(out / SHEET, out / PREVIEW, cfg.sheet.preview.width_px)
    return write_meta(out, cfg, {"sheet_json": SHEET_JSON,
                                 "preview": PREVIEW if has_png else None, **extra})


def write_meta(out: Path, cfg: Config, extra: dict) -> Path:
    """meta.json прогона: шаги — те, чьи файлы есть в папке; extra заменяет общие поля."""
    meta = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(), "genfacade": version("genfacade"),
        "sheet_json": None, "preview": None,
        "steps": [_written(s, out)._asdict() for s in STEPS],
        **extra,
        # Итоговые настройки целиком: прогон повторяется без исходной папки конфига.
        "config": cfg.model_dump(mode="json"),
    }
    (out / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return out


def _written(step: Step, out: Path) -> Step:
    """Шаг без файлов, которых прогон не написал."""
    return step._replace(**{k: None for k in FILE_FIELDS
                            if getattr(step, k) and not (out / getattr(step, k)).exists()})


def git_sha() -> str | None:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,  # noqa: S603, S607
                             text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return res.stdout.strip()
