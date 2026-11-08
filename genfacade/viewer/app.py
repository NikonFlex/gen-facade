"""Сервер смотрелки: планы и прогоны, примеры датасета, режимы и подписи, файлы трассы, слепая
проверка листов глазами (/review, gf#268), каталог видов (/catalog, gf#354), правила (/rules,
gf#356).

Страница ничего не считает сама: SVG рисует тот же render/, что и на выходе
(docs/decisions.md, 29.09 «трасса каждого шага и веб-смотрелка»).
"""

import json
from importlib.resources import files
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from genfacade import pipeline
from genfacade.config import Config, Review
from genfacade.datasets import preview, store
from genfacade.metrics import calibrate
from genfacade.plan.genplan_svg import PlanError
from genfacade.render.house3d import house_3d
from genfacade.render.svg import sheet_svg
from genfacade.schema import FacadeSheet, Mode, Refusal, Sample, Source, refusal_record
from genfacade.viewer import catalog, data_page, houses, markup, newhouse, review, rules

STATIC = files(__package__).joinpath("static")
REFERENCE_SLOT = "ref"  # место настоящего листа на странице проверки


class RunRequest(BaseModel):
    """План с описанием (plan_run): план — из списка по имени или присланный SVG (svg)."""

    plan_run: pipeline.PlanRun
    svg: str | None = None


def create_app(cfg: Config, checked: Path | None = None, marked: Path | None = None) -> FastAPI:
    """checked — папка `genfacade realtest` для слепой проверки; None — страница /review пуста.
    marked — папка разметки для правки в браузере (/markup, gf#348); None — из настроек."""
    runs_dir = cfg.viewer.paths.runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="GenFacade · смотрелка")
    app.middleware("http")(_revalidate_page)
    app.exception_handler(RequestValidationError)(_invalid_request)
    _api(app, cfg, runs_dir)
    _samples_api(app, cfg)
    _review_api(app, cfg, checked)
    markup.api(app, cfg, marked or cfg.viewer.markup.folder)
    catalog.api(app, cfg)
    newhouse.api(app, cfg)
    rules.api(app, cfg)
    app.mount("/files", StaticFiles(directory=runs_dir), name="files")
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(STATIC.joinpath("index.html")))

    @app.get("/review")
    def review_page() -> FileResponse:
        return FileResponse(str(STATIC.joinpath("review.html")))

    @app.get("/markup")
    def markup_page() -> FileResponse:
        return FileResponse(str(STATIC.joinpath("markup.html")))

    @app.get("/rules")
    def rules_page() -> FileResponse:
        return FileResponse(str(STATIC.joinpath("rules.html")))

    @app.get("/catalog")
    def catalog_page() -> FileResponse:
        return FileResponse(str(STATIC.joinpath("catalog.html")))

    return app


async def _revalidate_page(request: Request, call_next):
    """Страница и её JS/CSS — всегда с перепроверкой: иначе после обновления браузер
    берёт старый app.js к новому index.html, и страница ломается (хозяин, 30.09).
    Файлы прогонов не меняются — их кэш не трогаем."""
    response = await call_next(request)
    if not request.url.path.startswith("/files/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def refuse(status: int, code: Refusal, detail: str = "") -> HTTPException:
    """Отказ смотрелки: detail — `{code, text, detail}`, страница рисует его как есть и своих
    списков кодов не держит (docs/clean-contour.md, п. 17)."""
    return HTTPException(status, refusal_record(code, detail))


async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Ошибки схемы запроса — тем же отказом, по строке на поле; «Value error, » — служебная
    приставка pydantic, человеку она ничего не говорит."""
    lines = [f"{'.'.join(str(p) for p in e['loc'] if p not in ('body', 'sheet'))}: "
             f"{e['msg'].removeprefix('Value error, ')}" for e in exc.errors()]
    return JSONResponse({"detail": refusal_record(Refusal.INVALID_REQUEST, lines)}, 422)


def _api(app: FastAPI, cfg: Config, runs_dir: Path) -> None:
    @app.get("/api/runs")
    def runs() -> list[dict]:
        return _runs(runs_dir, cfg)

    @app.get("/api/runs/{run_id}")
    def run_meta(run_id: str) -> dict:
        return json.loads((_run_dir(runs_dir, run_id) / pipeline.META).read_text())

    @app.get("/api/runs/{run_id}/house3d")
    def run_house(run_id: str) -> dict:
        return _house(_run_dir(runs_dir, run_id), cfg)

    @app.get("/api/runs/{run_id}/sheet.svg")
    def run_sheet(run_id: str) -> Response:
        """Лист прогона по sheet.json — картинка карточки, когда PNG нет (viewer/houses.py)."""
        svg = sheet_svg(_run_sheet(_run_dir(runs_dir, run_id)), cfg)
        return Response(svg, media_type="image/svg+xml")

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
            raise refuse(404, Refusal.NO_PLAN, name)
        return FileResponse(str(found[name]), media_type="image/svg+xml")

    @app.post("/api/runs")
    def start(req: RunRequest) -> dict:
        return {"id": _start_plan(req.plan_run, req.svg, cfg).name}


def _samples_api(app: FastAPI, cfg: Config) -> None:
    @app.get("/api/data")
    def data() -> dict:
        return data_page.overview(cfg)

    @app.get("/api/samples")
    def samples() -> list[dict]:
        return _samples(cfg)

    @app.post("/api/samples/{source}/{sample_id}")
    def open_sample(source: Source, sample_id: str) -> dict:
        # Папка просмотра рисуется заново при каждом открытии — тем же render/.
        return {"id": preview.render(_sample(source, sample_id, cfg), cfg).name}

    @app.get("/api/samples/{source}/{sample_id}/sheet.svg")
    def sample_sheet(source: Source, sample_id: str) -> Response:
        svg = sheet_svg(_sample(source, sample_id, cfg).sheet, cfg)
        return Response(svg, media_type="image/svg+xml")


def _review_api(app: FastAPI, cfg: Config, root: Path | None) -> None:
    settings = cfg.viewer.review

    @app.get("/api/review")
    def review_items() -> dict:
        """Дома × режимы: сколько мест и отметки; чья строка на месте — не отдаётся. reference —
        показывать ли настоящий дом отдельно, modes — сколько режимов у проверки, done — размечен
        ли дом целиком (считает сервер)."""
        if root is None:
            return {"folder": None, "items": []}
        found = review.marks(root)
        n = len(settings.rows)
        items = [{"mode": m, "house": h, "slots": n, "done": review.is_done(found, m, h, n),
                  "marks": {s: _public(found.get(review.key(m, h, s))) for s in range(n)}}
                 for m in settings.modes for h in review.houses(root)]
        return {"folder": str(root), "items": items, "reference": settings.reference,
                "modes": len(settings.modes)}

    @app.get("/api/review/{mode}/{house}/{slot}/sheet.svg")
    def review_sheet(mode: Mode, house: str, slot: str) -> Response:
        """Лист места (A, B… — номер) или настоящий (`ref`); отказ модели — 422 с её кодом."""
        place = (mode, house, slot)
        return Response(sheet_svg(_sheet(root, place, settings), cfg),
                        media_type="image/svg+xml")

    @app.get("/api/review/{mode}/{house}/{slot}/house3d")
    def review_house(mode: Mode, house: str, slot: str) -> dict:
        """Дом места объёмом, как вкладка «Дом в 3D» (хозяин 03.11: проверять по 3D-модели)."""
        try:
            return house_3d(_sheet(root, (mode, house, slot), settings), cfg)
        except PlanError as e:
            raise refuse(404, Refusal.HOUSE_NOT_BUILT, str(e)) from e

    @app.put("/api/review/{mode}/{house}/{slot}")
    def review_mark(mode: Mode, house: str, slot: int, mark: review.Mark) -> dict:
        done = _guarded(lambda: review.save(_root(root), mode, house, slot, mark, settings))
        return {"saved": True, "done": done}


def _sheet(root: Path | None, place: tuple[Mode, str, str], settings: Review) -> FacadeSheet:
    """Лист места проверки (режим, дом, место); отказ модели — 422 с её кодом."""
    mode, house, slot = place
    row = _row(root, place, settings)
    got = _guarded(lambda: review.sheet(_root(root), mode, house, row))
    if not isinstance(got, FacadeSheet):
        raise HTTPException(422, got)
    return got


def _row(root: Path | None, place: tuple[Mode, str, str], settings: Review) -> str:
    """Папка строки на месте: `ref` — настоящий дом, номер — строка по перемешанному порядку."""
    mode, house, slot = place
    if slot == REFERENCE_SLOT:
        return calibrate.REFERENCE
    order = _guarded(lambda: review.slots(_root(root), mode, house, settings))
    if not slot.isdigit() or int(slot) >= len(order):
        raise refuse(404, Refusal.NO_REVIEW_ITEM, f"нет места {slot!r}")
    return order[int(slot)]


def _root(root: Path | None) -> Path:
    if root is None:
        raise refuse(404, Refusal.NO_REVIEW)
    return root


def _guarded(call):
    try:
        return call()
    except review.Missing as e:
        raise HTTPException(404, e.record()) from e


def _public(mark: dict | None) -> dict | None:
    """Отметка без строки: страница не должна знать, чья строка на месте."""
    return None if mark is None else {"ok": mark["ok"], "why": mark["why"]}


def _samples(cfg: Config) -> list[dict]:
    """Источники, в которых есть примеры: опись и первые имена для вкладки «Датасеты»."""
    root, shown = cfg.data.paths.samples_dir, cfg.viewer.samples.shown
    return [{"ids": store.ids(root, source)[:shown], **store.load_manifest(root, source)}
            for source in Source if store.ids(root, source)]


def _sample(source: Source, sample_id: str, cfg: Config) -> Sample:
    root = cfg.data.paths.samples_dir
    if sample_id not in store.ids(root, source):
        raise refuse(404, Refusal.NO_SAMPLE, f"{source}/{sample_id}")
    return store.read(root, source, sample_id)


def _options(cfg: Config) -> dict:
    """Режимы и подписи к классам, ролям и типам окон: страница своих списков не держит."""
    labels = cfg.viewer.labels
    modes = [{"value": m, **labels.mode[m].model_dump()} for m in Mode]
    return {"modes": modes, "default_mode": pipeline.PlanRun.model_fields["mode"].default,
            "house3d": cfg.viewer.house3d.model_dump(),
            **labels.model_dump(mode="json", exclude={"mode"})}


def _run_sheet(folder: Path) -> FacadeSheet:
    """Лист прогона; прогон до листа не дошёл — 404 с причиной."""
    meta = json.loads((folder / pipeline.META).read_text())
    if not meta.get("sheet_json"):
        raise refuse(404, Refusal.NO_SHEET)
    return FacadeSheet.model_validate_json((folder / meta["sheet_json"]).read_text())


def _house(folder: Path, cfg: Config) -> dict:
    """Дом объёмом по листу прогона; нет листа или контур не ортогональный — 404 с причиной."""
    sheet = _run_sheet(folder)
    try:
        return house_3d(sheet, cfg)
    except PlanError as e:
        raise refuse(404, Refusal.HOUSE_NOT_BUILT, str(e)) from e


def _plans(cfg: Config) -> dict[str, Path]:
    found = {}
    for folder in cfg.viewer.paths.plans_dirs:
        for path in sorted(folder.glob("*.svg")):
            found.setdefault(path.stem, path)
    return found


def _start_plan(run: pipeline.PlanRun, svg: str | None, cfg: Config) -> Path:
    """План из списка по имени или присланный SVG; отказ — 400 с причиной, а трасса до отказа
    с meta.json остаётся в списке прогонов."""
    plans = _plans(cfg)
    if svg is None and run.plan not in plans:
        raise refuse(404, Refusal.NO_PLAN, run.plan)
    text = svg if svg is not None else plans[run.plan].read_text()
    out = pipeline.new_run_dir(cfg.viewer.paths.runs_dir, Path(run.plan).stem)
    try:
        return pipeline.generate(run, text, out, cfg)
    except pipeline.REFUSALS as e:
        raise HTTPException(400, e.record()) from e


def _runs(runs_dir: Path, cfg: Config) -> list[dict]:
    """Прогоны с трассой карточками страницы «Дома» (viewer/houses.py), новые сверху; папки без
    meta.json со списком шагов и просмотры примеров датасета — пропуск."""
    result = []
    for meta_path in sorted(runs_dir.glob(f"*/{pipeline.META}"), reverse=True):
        meta = json.loads(meta_path.read_text())
        if "steps" in meta and not preview.is_preview(meta):
            result.append(houses.card(meta_path.parent, meta, cfg))
    return result


def _run_dir(runs_dir: Path, run_id: str) -> Path:
    path = runs_dir / run_id
    if not pipeline.RUN_ID.match(run_id) or not (path / pipeline.META).exists():
        raise refuse(404, Refusal.NO_RUN, run_id)
    return path
