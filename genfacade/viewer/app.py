"""Сервер смотрелки: список домов и прогонов, запуск конвейера, файлы трассы.

Страница ничего не считает сама: SVG рисует тот же render/, что и на выходе
(docs/decisions.md, 29.09 «трасса каждого шага и веб-смотрелка»).
"""

import json
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from genfacade import pipeline
from genfacade.config import Config
from genfacade.plan.genplan_svg import PlanError
from genfacade.schema import FacadeSheet

STATIC = files(__package__).joinpath("static")


class RunRequest(BaseModel):
    """Запустить дом из списка (house), присланный JSON (sheet) под именем name или
    план с описанием (plan_run): план — из списка по имени или присланный SVG (svg)."""

    house: str | None = None
    sheet: FacadeSheet | None = None
    name: str = "house"
    plan_run: pipeline.PlanRun | None = None
    svg: str | None = None


def create_app(cfg: Config) -> FastAPI:
    runs_dir = cfg.viewer.paths.runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="GenFacade · смотрелка")
    app.middleware("http")(_revalidate_page)
    _api(app, cfg, runs_dir)
    app.mount("/files", StaticFiles(directory=runs_dir), name="files")
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(STATIC.joinpath("index.html")))

    return app


async def _revalidate_page(request: Request, call_next):
    """Страница и её JS/CSS — всегда с перепроверкой: иначе после обновления браузер
    берёт старый app.js к новому index.html, и страница ломается (хозяин, 30.09).
    Файлы прогонов не меняются — их кэш не трогаем."""
    response = await call_next(request)
    if not request.url.path.startswith("/files/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def _api(app: FastAPI, cfg: Config, runs_dir: Path) -> None:
    @app.get("/api/houses")
    def houses() -> list[dict]:
        return [_house_card(name, path) for name, path in _houses(cfg).items()]

    @app.get("/api/runs")
    def runs() -> list[dict]:
        return _runs(runs_dir)

    @app.get("/api/runs/{run_id}")
    def run_meta(run_id: str) -> dict:
        return json.loads((_run_dir(runs_dir, run_id) / pipeline.META).read_text())

    @app.get("/api/plans")
    def plans() -> list[dict]:
        return [{"name": name} for name in _plans(cfg)]

    @app.get("/api/plans/{name}")
    def plan_file(name: str) -> FileResponse:
        found = _plans(cfg)
        if name not in found:
            raise HTTPException(404, f"нет плана {name!r}")
        return FileResponse(str(found[name]), media_type="image/svg+xml")

    @app.post("/api/runs")
    def start(req: RunRequest) -> dict:
        if req.plan_run is not None:
            return {"id": _start_plan(req.plan_run, req.svg, cfg).name}
        house, name, source = _resolve(req, cfg)
        out = pipeline.new_run_dir(runs_dir, name)
        pipeline.run(house, out, cfg, source=source)
        return {"id": out.name}


def _plans(cfg: Config) -> dict[str, Path]:
    found = {}
    for folder in cfg.viewer.paths.plans_dirs:
        for path in sorted(folder.glob("*.svg")):
            found.setdefault(path.stem, path)
    return found


def _start_plan(run: pipeline.PlanRun, svg: str | None, cfg: Config) -> Path:
    """План из списка по имени или присланный SVG; дефектный план — 400 с причиной."""
    plans = _plans(cfg)
    if svg is None and run.plan not in plans:
        raise HTTPException(404, f"нет плана {run.plan!r}")
    text = svg if svg is not None else plans[run.plan].read_text()
    out = pipeline.new_run_dir(cfg.viewer.paths.runs_dir, Path(run.plan).stem)
    try:
        return pipeline.generate(run, text, out, cfg)
    except PlanError as e:
        raise HTTPException(400, f"план отклонён: {e}") from e


def _houses(cfg: Config) -> dict[str, Path]:
    found = {}
    for folder in cfg.viewer.paths.houses_dirs:
        for path in sorted(folder.glob("*.json")):
            found.setdefault(path.stem, path)
    return found


def _house_card(name: str, path: Path) -> dict:
    """Сводка для списка домов: этажи, крыша, габариты — без запуска конвейера."""
    sheet = FacadeSheet.model_validate_json(path.read_text())
    spec, sides = sheet.spec, [f.side for f in sheet.facades]
    return {
        "name": name, "floors": spec.floors, "roof": spec.roof.kind, "style": spec.style,
        "size_m": [sides[0].length_m, sides[1].length_m] if len(sides) > 1 else [],
        "palette": [m.color for m in spec.materials if m.color],
    }


def _resolve(req: RunRequest, cfg: Config) -> tuple[FacadeSheet, str, str]:
    if req.sheet is not None:
        return req.sheet, req.name, "смотрелка: присланный JSON"
    houses = _houses(cfg)
    if req.house not in houses:
        raise HTTPException(404, f"нет дома {req.house!r}")
    path = houses[req.house]
    return FacadeSheet.model_validate_json(path.read_text()), req.house, str(path)


def _runs(runs_dir: Path) -> list[dict]:
    """Прогоны с трассой, новые сверху; папки без meta.json со списком шагов — пропуск."""
    result = []
    for meta_path in sorted(runs_dir.glob(f"*/{pipeline.META}"), reverse=True):
        meta = json.loads(meta_path.read_text())
        if "steps" in meta:
            result.append({"id": meta_path.parent.name, "source": meta["source"],
                           "date": meta["date"], "preview": meta["preview"]})
    return result


def _run_dir(runs_dir: Path, run_id: str) -> Path:
    path = runs_dir / run_id
    if not pipeline.RUN_ID.match(run_id) or not (path / pipeline.META).exists():
        raise HTTPException(404, f"нет прогона {run_id!r}")
    return path
