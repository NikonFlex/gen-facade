"""Конвейер и его трасса: выход каждого шага — в папку прогона (generation.md, п. 1, 9, 10).

`generate`: SVG-план GenPlan + текст → шаги 1–6. Смотрелка и CLI читают одно и то же — папку
прогона с `meta.json`, где перечислены шаги и файлы.
"""

import json
import re
import subprocess  # noqa: S404 — только git rev-parse
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from pydantic import BaseModel

from genfacade.config import Config
from genfacade.models import stub
from genfacade.plan.preprocess import preprocess
from genfacade.render.plan_svg import plan_svg
from genfacade.render.preview import to_png
from genfacade.render.svg import sheet_svg
from genfacade.schema import FacadeSheet, HouseSpec, Mode, Plan, SideFacade
from genfacade.snap import snap
from genfacade.unfold import unfold
from genfacade.validate import errors, validate

# Семь шагов схемы (docs/assets/facade-modules.png); седьмой — позже, вместе с Егором.
STEPS = {1: "Параметры дома", 2: "План", 3: "Развёртка", 4: "Раскладка стен",
         5: "Сетка и проверка", 6: "Лист фасадов"}
UNFOLD, SHEET, SHEET_JSON, PREVIEW, META = (
    "03_unfold.svg", "06_sheet.svg", "sheet.json", "preview.png", "meta.json")
REQUEST, INPUT_PLAN, SPEC, PLAN_JSON, PLAN_SVG, LAYOUT, SNAPPED, VIOLATIONS = (
    "request.json", "input_plan.svg", "01_spec.json", "02_plan.json", "02_plan.svg",
    "04_layout.svg", "05_snapped.svg", "violations.json")
STEP_FILES = {1: SPEC, 2: PLAN_SVG, 3: UNFOLD, 4: LAYOUT, 5: SNAPPED, 6: SHEET}
RUN_ID = re.compile(r"^[\w.-]+$")  # имя папки прогона: без / и .., чтобы не выйти из runs_dir


class PlanRun(BaseModel):
    """Запрос на прогон (task.md, Request): план — имя или путь, откуда он пришёл.

    seed нет: до модели всё детерминировано; появится с ней (этап 4, хозяин 30.09).
    """

    plan: str
    text: str
    mode: Mode = "with_openings"


def new_run_dir(runs_dir: Path, name: str) -> Path:
    """Свободная папка <время>-<имя>; два запуска в одну секунду получают суффикс."""
    base = f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^\w.-]', '_', name)}"
    out, n = runs_dir / base, 2
    while out.exists():
        out, n = runs_dir / f"{base}-{n}", n + 1
    return out


def generate(req: PlanRun, svg: str, out: Path, cfg: Config) -> Path:
    """План GenPlan + текст → трасса шагов 1–6.

    Дефектный план — PlanError, вход, на который не ответит модель (стаб), — ModelError.
    """
    out.mkdir(parents=True, exist_ok=True)
    (out / INPUT_PLAN).write_text(svg)
    (out / REQUEST).write_text(req.model_dump_json(indent=2))
    bare = _prepare(req, svg, out, cfg)
    # Шаги 4–5. Брак не перегенерируем: стаб детерминирован, повтор дал бы то же самое;
    # «брак — заново» (generation.md, п. 1) вернётся с моделью. Нарушения — в трассу.
    raw = stub.layout_all(bare, stub.LayoutContext(bare.spec, req.mode, req.text))
    sheet = snap(raw, cfg.checks)
    violations = validate(sheet, cfg.checks)
    (out / LAYOUT).write_text(sheet_svg(raw, cfg, violations=[], annotations=False))
    (out / SNAPPED).write_text(sheet_svg(sheet, cfg, violations=violations, annotations=False))
    (out / VIOLATIONS).write_text(json.dumps(
        [v.model_dump() for v in violations], ensure_ascii=False, indent=2))
    extra = {
        "source": req.plan, "input": REQUEST, "plan_input": INPUT_PLAN, "violations": VIOLATIONS,
        "request": req.model_dump(),
        "errors": len(errors(violations)), "warnings": len(violations) - len(errors(violations)),
    }
    return _finish(sheet, out, cfg, extra)


def walls(spec: HouseSpec, plan: Plan) -> FacadeSheet:
    """Шаг 3: пустые прямоугольники стен всех сторон плана, без крыши."""
    return unfold(FacadeSheet(spec=spec, facades=[SideFacade(side=s) for s in plan.sides]))


def _prepare(req: PlanRun, svg: str, out: Path, cfg: Config) -> FacadeSheet:
    """Шаги 1–3: параметры дома, план, развёртка — с трассой.

    Шаг 1 — модель (пока стаб): текст → HouseSpec.
    """
    plan = preprocess(svg, req.mode, cfg.plan)
    spec = stub.spec_model(req.text)
    # цвета — для смотрелки: у палитры без цвета берётся цвет вида из библиотеки
    colors = {m.id: m.color or cfg.library.kinds.get(m.kind) for m in spec.materials}
    (out / SPEC).write_text(json.dumps({"spec": spec.model_dump(), "colors": colors},
                                       ensure_ascii=False, indent=2))
    (out / PLAN_JSON).write_text(plan.model_dump_json(indent=2))
    (out / PLAN_SVG).write_text(plan_svg(plan, cfg))
    bare = walls(spec, plan)
    (out / UNFOLD).write_text(sheet_svg(bare, cfg, annotations=False))
    return bare


def _finish(sheet: FacadeSheet, out: Path, cfg: Config, extra: dict) -> Path:
    """Шаг 6 и meta.json: лист, JSON, PNG; extra — поля прогона."""
    (out / SHEET).write_text(sheet_svg(sheet, cfg))
    (out / SHEET_JSON).write_text(sheet.model_dump_json(indent=2))
    has_png = to_png(out / SHEET, out / PREVIEW, cfg.sheet.preview.width_px)
    meta = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "git_sha": _git_sha(), "genfacade": version("genfacade"),
        "sheet_json": SHEET_JSON, "preview": PREVIEW if has_png else None,
        "steps": [{"n": n, "title": t, "file": STEP_FILES[n]} for n, t in STEPS.items()],
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
