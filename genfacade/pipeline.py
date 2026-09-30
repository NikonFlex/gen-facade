"""Конвейер и его трасса: выход каждого шага — в папку прогона (generation.md, п. 1, 9, 10).

Два входа. `generate` — настоящий: SVG-план GenPlan + текст → шаги 1–6. `run` — дом из JSON
(этап 0, тестовые дома): только развёртка и лист. Смотрелка и CLI читают одно и то же — папку
прогона с `meta.json`, где перечислены шаги и файлы.
"""

import json
import re
import subprocess  # noqa: S404 — только git rev-parse
from dataclasses import dataclass
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel

from genfacade.config import Config
from genfacade.layout.rule import LayoutContext, place_all, window_size
from genfacade.plan.preprocess import preprocess
from genfacade.render.plan_svg import plan_svg
from genfacade.render.preview import to_png
from genfacade.render.svg import sheet_svg
from genfacade.schema import FacadeSheet, HouseSpec, Mode, Plan, Side, SideFacade, Violation
from genfacade.snap import snap
from genfacade.spec.rule import from_text
from genfacade.unfold import unfold
from genfacade.validate import errors, validate

# Семь шагов схемы (docs/assets/facade-modules.png); седьмой — позже, вместе с Егором.
STEPS = {1: "Параметры дома", 2: "План", 3: "Развёртка", 4: "Раскладка стен",
         5: "Сетка и проверка", 6: "Лист фасадов"}
INPUT, UNFOLD, SHEET, SHEET_JSON, PREVIEW, META = (
    "input.json", "03_unfold.svg", "06_sheet.svg", "sheet.json", "preview.png", "meta.json")
REQUEST, INPUT_PLAN, SPEC, PLAN_JSON, PLAN_SVG, LAYOUT, SNAPPED, VIOLATIONS = (
    "request.json", "input_plan.svg", "01_spec.json", "02_plan.json", "02_plan.svg",
    "04_layout.svg", "05_snapped.svg", "violations.json")
RUN_ID = re.compile(r"^[\w.-]+$")  # имя папки прогона: без / и .., чтобы не выйти из runs_dir


class PlanRun(BaseModel):
    """Запрос на прогон (task.md, Request): план — имя или путь, откуда он пришёл."""

    plan: str
    text: str
    mode: Mode = "with_openings"
    seed: int = 0


@dataclass(frozen=True)
class Attempt:
    """Одна попытка шагов 4–5: раскладка, после привязки, нарушения."""

    seed: int
    raw: FacadeSheet
    sheet: FacadeSheet
    violations: list[Violation]


def new_run_dir(runs_dir: Path, name: str) -> Path:
    """Свободная папка <время>-<имя>; два запуска в одну секунду получают суффикс."""
    base = f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^\w.-]', '_', name)}"
    out, n = runs_dir / base, 2
    while out.exists():
        out, n = runs_dir / f"{base}-{n}", n + 1
    return out


def generate(req: PlanRun, svg: str, out: Path, cfg: Config) -> Path:
    """План GenPlan + текст → трасса шагов 1–6; дефектный план — PlanError с причиной."""
    out.mkdir(parents=True, exist_ok=True)
    (out / INPUT_PLAN).write_text(svg)
    (out / REQUEST).write_text(req.model_dump_json(indent=2))
    bare, found = _prepare(req, svg, out, cfg)
    attempts = _attempts(bare, req, cfg)
    best = min(attempts, key=lambda a: len(errors(a.violations)))
    (out / LAYOUT).write_text(sheet_svg(best.raw, cfg, violations=[]))
    (out / SNAPPED).write_text(sheet_svg(best.sheet, cfg, violations=best.violations))
    (out / VIOLATIONS).write_text(json.dumps(
        [v.model_dump() for v in best.violations], ensure_ascii=False, indent=2))
    files = {1: SPEC, 2: PLAN_SVG, 3: UNFOLD, 4: LAYOUT, 5: SNAPPED, 6: SHEET}
    extra = {
        "kind": "plan", "input": REQUEST, "plan_input": INPUT_PLAN, "violations": VIOLATIONS,
        "request": req.model_dump(), "seed_used": best.seed, "from_text": found,
        "attempts": [{"seed": a.seed, "errors": len(errors(a.violations)),
                      "warnings": len(a.violations) - len(errors(a.violations))} for a in attempts],
    }
    return _finish(best.sheet, out, cfg, (files, extra))


def run(house: FacadeSheet, out: Path, cfg: Config, source: str) -> Path:
    """Дом из JSON (этап 0): развёртка и лист с трассой в out; source — откуда дом."""
    out.mkdir(parents=True, exist_ok=True)
    (out / INPUT).write_text(house.model_dump_json(indent=2, exclude_none=True))
    sheet = unfold(house, cfg.library.roof.thickness_m)
    bare = [f.model_copy(update={"elements": [], "zones": []}) for f in sheet.facades]
    (out / UNFOLD).write_text(sheet_svg(sheet.model_copy(update={"facades": bare}), cfg))
    extra = {"kind": "house", "input": INPUT, "source": source}
    return _finish(sheet, out, cfg, ({3: UNFOLD, 6: SHEET}, extra))


def ridge_along_longest(spec: HouseSpec, sides: list[Side]) -> HouseSpec:
    """Конёк — вдоль длинной стороны плана: ось зависит от плана, текст её не знает."""
    longest = max(sides, key=lambda s: s.length_m)
    roof = spec.roof.model_copy(update={"ridge_axis": "x" if longest.runs_along_x else "y"})
    return spec.model_copy(update={"roof": roof})


def walls(spec: HouseSpec, plan: Plan, cfg: Config) -> FacadeSheet:
    """Шаг 3: пустые стены всех сторон плана с силуэтами из HouseSpec."""
    bare = FacadeSheet(spec=spec, facades=[SideFacade(side=s) for s in plan.sides])
    return unfold(bare, cfg.library.roof.thickness_m)


def _prepare(req: PlanRun, svg: str, out: Path, cfg: Config) -> tuple[FacadeSheet, dict]:
    """Шаги 1–3: параметры дома, план, развёртка — с трассой."""
    plan = preprocess(svg, req.mode, cfg.plan)
    spec, found = from_text(req.text, cfg.spec)
    spec = ridge_along_longest(spec, plan.sides)
    found["window_size"] = window_size(req.text, cfg.layout)[1]
    # цвета — для смотрелки: у палитры правила цвет не задан, берётся цвет вида из библиотеки
    colors = {m.id: m.color or cfg.library.kinds.get(m.kind) for m in spec.materials}
    (out / SPEC).write_text(json.dumps({"spec": spec.model_dump(), "from_text": found,
                                        "colors": colors}, ensure_ascii=False, indent=2))
    (out / PLAN_JSON).write_text(plan.model_dump_json(indent=2))
    (out / PLAN_SVG).write_text(plan_svg(plan, cfg))
    bare = walls(spec, plan, cfg)
    (out / UNFOLD).write_text(sheet_svg(bare, cfg))
    return bare, found


def _attempts(bare: FacadeSheet, req: PlanRun, cfg: Config) -> list[Attempt]:
    """Шаги 4–5 с повтором (generation.md, п. 1): брак — заново со следующим seed.

    Не больше max_attempts; и стоп, если повтор дал те же ошибки — их не лечит раскладка
    (окно плана в запретной зоне — дефект плана, plan-input.md «Открыто»).
    """
    out: list[Attempt] = []
    for k in range(cfg.checks.max_attempts):
        ctx = LayoutContext(bare.spec, req.mode, req.text, req.seed + k)
        raw = place_all(bare, ctx, cfg.layout)
        sheet = snap(raw, cfg.checks)
        out.append(Attempt(ctx.seed, raw, sheet, validate(sheet, cfg.checks)))
        now = _error_keys(out[-1])
        if not now or (len(out) > 1 and now == _error_keys(out[-2])):
            break
    return out


def _error_keys(a: Attempt) -> set[tuple]:
    return {(v.rule, v.side, v.element) for v in errors(a.violations)}


def _finish(sheet: FacadeSheet, out: Path, cfg: Config, trace: tuple[dict, dict]) -> Path:
    """Шаг 6 и meta.json: лист, JSON, PNG; trace — файлы шагов и поля прогона."""
    files, extra = trace
    (out / SHEET).write_text(sheet_svg(sheet, cfg))
    (out / SHEET_JSON).write_text(sheet.model_dump_json(indent=2))
    has_png = to_png(out / SHEET, out / PREVIEW, cfg.sheet.preview.width_px)
    meta = {
        "source": extra.pop("source", None) or extra["request"]["plan"],
        "date": datetime.now().isoformat(timespec="seconds"),
        "git_sha": _git_sha(), "genfacade": version("genfacade"),
        "sheet_json": SHEET_JSON, "preview": PREVIEW if has_png else None,
        "steps": [{"n": n, "title": t, "file": files.get(n)} for n, t in STEPS.items()],
        **extra,
        # Итоговые настройки целиком: прогон повторяется без исходной папки конфига.
        "config": cfg.model_dump(mode="json"),
    }
    (out / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return out


def _git_sha() -> str | None:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,  # noqa: S603, S607
                             text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return res.stdout.strip()
