"""Сервер смотрелки: планы и прогоны, примеры датасета, режимы и подписи, файлы трассы.

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
from genfacade.datasets import preview, store
from genfacade.models.stub import ModelError
from genfacade.plan.genplan_svg import PlanError
from genfacade.schema import Mode, Source

STATIC = files(__package__).joinpath("static")


class RunRequest(BaseModel):
    """План с описанием (plan_run): план — из списка по имени или присланный SVG (svg)."""

    plan_run: pipeline.PlanRun
    svg: str | None = None


def create_app(cfg: Config) -> FastAPI:
    runs_dir = cfg.viewer.paths.runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="GenFacade · смотрелка")
    app.middleware("http")(_revalidate_page)
    _api(app, cfg, runs_dir)
    _samples_api(app, cfg)
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
    @app.get("/api/runs")
    def runs() -> list[dict]:
        return _runs(runs_dir)

    @app.get("/api/runs/{run_id}")
    def run_meta(run_id: str) -> dict:
        return json.loads((_run_dir(runs_dir, run_id) / pipeline.META).read_text())

    @app.get("/api/options")
    def options() -> dict:
        return _options(cfg)

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
        return {"id": _start_plan(req.plan_run, req.svg, cfg).name}


def _samples_api(app: FastAPI, cfg: Config) -> None:
    @app.get("/api/samples")
    def samples() -> list[dict]:
        return _samples(cfg)

    @app.post("/api/samples/{source}/{sample_id}")
    def open_sample(source: Source, sample_id: str) -> dict:
        return {"id": _open_sample(source, sample_id, cfg).name}


def _samples(cfg: Config) -> list[dict]:
    """Источники, в которых есть примеры: сколько их и первые имена для главной."""
    root, shown = cfg.data.paths.samples_dir, cfg.viewer.samples.shown
    found = [(source, store.ids(root, source)) for source in Source]
    return [{"source": s, "count": len(names), "ids": names[:shown]} for s, names in found if names]


def _open_sample(source: Source, sample_id: str, cfg: Config) -> Path:
    """Пример → папка просмотра; рисуется заново при каждом открытии — тем же render/."""
    root = cfg.data.paths.samples_dir
    if sample_id not in store.ids(root, source):
        raise HTTPException(404, f"нет примера {source}/{sample_id}")
    return preview.render(store.read(root, source, sample_id), cfg)


def _options(cfg: Config) -> dict:
    """Режимы и подписи к классам, ролям и типам окон: страница своих списков не держит."""
    labels = cfg.viewer.labels
    modes = [{"value": m, **labels.mode[m].model_dump()} for m in Mode]
    return {"modes": modes, "default_mode": pipeline.PlanRun.model_fields["mode"].default,
            **labels.model_dump(mode="json", exclude={"mode"})}


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
    except ModelError as e:
        raise HTTPException(400, f"модель не ответила: {e}") from e


def _runs(runs_dir: Path) -> list[dict]:
    """Прогоны с трассой, новые сверху; папки без meta.json со списком шагов и просмотры
    примеров датасета — пропуск."""
    result = []
    for meta_path in sorted(runs_dir.glob(f"*/{pipeline.META}"), reverse=True):
        meta = json.loads(meta_path.read_text())
        if "steps" in meta and "sample" not in meta:
            result.append({"id": meta_path.parent.name, "source": meta["source"],
                           "date": meta["date"], "preview": meta["preview"]})
    return result


def _run_dir(runs_dir: Path, run_id: str) -> Path:
    path = runs_dir / run_id
    if not pipeline.RUN_ID.match(run_id) or not (path / pipeline.META).exists():
        raise HTTPException(404, f"нет прогона {run_id!r}")
    return path
