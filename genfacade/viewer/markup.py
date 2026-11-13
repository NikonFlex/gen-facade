"""Страница /markup: проверка и правка автоматической разметки домов строим.дом.рф (gf#348).

Дом — `<id>.toml` папки разметки. Страница рисует рамки поверх листов, а что с ними делать,
решает сервер: правка применяется и пересчитывается в `datasets/markup_edit.py`, записывается в
TOML того же формата (`datasets/markup_toml.py`), состояние дома и время на него — в
`markup_queue.py`. Браузер ничего не пересчитывает: ни метры, ни этажи, ни состояние дома.
"""

import shutil
import tomllib
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import ValidationError, model_validator

from genfacade.config import Config
from genfacade.datasets import manual, markup_edit, markup_toml
from genfacade.schema import CheckState, Model, Refusal, Refused, RejectReason
from genfacade.viewer import markup_queue, markup_sheet, review

EDIT_LOCK = "markup.lock"  # правка файла разметки и решение о доме — одним замком, по одной
STATUS = {Refusal.NO_MARKUP_HOUSE: 404, Refusal.NO_MARKUP_SHEET: 404, Refusal.BAD_MARKUP_EDIT: 422,
          Refusal.BAD_CHECK_STEP: 409, Refusal.BAD_CHECK_STATE: 500}


class Decision(Model):
    """Решение о доме: «хорошо» (с правкой или без) или «негоден» с причиной из списка."""

    good: bool
    reason: RejectReason | None = None
    note: str = ""
    edit: markup_edit.Edit | None = None

    @model_validator(mode="after")
    def _reason_for_rejection(self) -> "Decision":
        if self.good == (self.reason is not None):
            raise ValueError("причина нужна негодному дому и только ему")
        return self


def api(app: FastAPI, cfg: Config, folder: Path) -> None:
    @app.get("/api/markup")
    def queue() -> dict:
        return _guard(lambda: _queue(cfg, folder))

    @app.post("/api/markup/{house}/open")
    def open_house(house: str) -> dict:
        return _guard(lambda: _open(cfg, folder, house))

    @app.post("/api/markup/{house}/preview")
    def preview(house: str, edit: markup_edit.Edit) -> dict:
        """Линии сторон после правки, без записи: потянули линию — стороны пересчитаны."""
        m = _guard(lambda: _edited(manual.read(_file(folder, house)), edit))
        return {"geometry": [markup_edit.geometry(m, k) for k in range(len(m.sides))]}

    @app.post("/api/markup/{house}/decision")
    def decision(house: str, decision: Decision) -> dict:
        return _guard(lambda: _decide(cfg, folder, house, decision))

    @app.get("/api/markup/{house}/page/{number}.jpg")
    def sheet(house: str, number: int) -> FileResponse:
        m = manual.read(_guard(lambda: _file(folder, house)))
        return FileResponse(str(_guard(lambda: markup_sheet.page_image(cfg, m, number))))


def _guard(call):
    """Отказ очереди, листа или правки — HTTP-ответом с кодом из контракта (`Refusal`)."""
    try:
        return call()
    except Refused as e:
        raise HTTPException(STATUS[e.code], e.record()) from e


def _file(folder: Path, house: str) -> Path:
    if house not in markup_queue.houses(folder):
        raise Refused(Refusal.NO_MARKUP_HOUSE, house)
    return folder / f"{house}.toml"


def _edited(m: manual.Markup, edit: markup_edit.Edit) -> manual.Markup:
    try:
        return markup_edit.apply(m, edit)
    except (ValueError, ValidationError) as e:
        raise Refused(Refusal.BAD_MARKUP_EDIT, str(e)) from e


def _queue(cfg: Config, folder: Path) -> dict:
    found = markup_queue.sync(cfg.viewer.markup, folder)
    items = [{"id": k, "state": r.state, "reason": r.reason, "seconds": r.seconds}
             for k, r in found.items()]
    return {"folder": str(folder), "items": items, "next": markup_queue.next_unchecked(found),
            "counts": markup_queue.counts(found), "options": _options(cfg)}


def _options(cfg: Config) -> dict:
    """Всё, что странице нужно знать о значениях: подписи, цвета, размеры — из конфига."""
    editor = cfg.viewer.markup
    return {"colors": editor.colors.model_dump(mode="json"),
            "labels": {"state": editor.labels.state, "reason": editor.labels.reason,
                       "level": editor.labels.level, "cls": cfg.viewer.labels.cls},
            "add_classes": editor.add_classes,
            "default_size_m": {k: list(v) for k, v in editor.default_size_m.items()},
            "min_box_m": editor.min_box_m}


def _open(cfg: Config, folder: Path, house: str) -> dict:
    """Дом для страницы: стороны с рамками и линиями в pt листа, состояние — как хранится."""
    editor = cfg.viewer.markup
    m = manual.read(_file(folder, house))
    markup_queue.sync(editor, folder)
    record = markup_queue.open_house(editor, folder, house)
    sides = [_side(cfg, m, k, house) for k in range(len(m.sides))]
    return {"id": house, "text": m.roof, "unit": m.unit, "state": record.state,
            "reason": record.reason, "note": record.note, "sides": sides}


def _side(cfg: Config, m: manual.Markup, k: int, house: str) -> dict:
    e = m.sides[k]
    width, height = markup_sheet.page_size(cfg, m, e.page)
    return {"view": e.view, "page": e.page, "image": f"/api/markup/{house}/page/{e.page}.jpg",
            "size": [width, height], "wall": list(e.wall), "geometry": markup_edit.geometry(m, k),
            "elements": [x.model_dump(mode="json") for x in e.elements],
            "zones": [z.model_dump(mode="json") for z in e.zones],
            "outline": e.outline, "roof": e.roof,
            "eaves": [s.model_dump(mode="json") for s in e.eaves]}


def _decide(cfg: Config, folder: Path, house: str, d: Decision) -> dict:
    """Решение о доме под замком: правка → TOML (исходная копия — один раз) → состояние."""
    editor, file = cfg.viewer.markup, _file(folder, house)
    with review.locked(folder, EDIT_LOCK):
        before = markup_queue.sync(editor, folder)[house].state
        edited = _changed(file, d.edit) if d.good and d.edit is not None else None
        state = _state(d.good, before, edited is not None)
        if edited is not None:
            _save(editor, folder, file, edited)
        record = markup_queue.decide(editor, folder, house, (state, d.reason, d.note))
        found = markup_queue.sync(editor, folder)
    return {"state": record.state, "seconds": record.seconds,
            "next": markup_queue.next_unchecked(found, house), "counts": markup_queue.counts(found),
            "assembly": _assembly(cfg, file)}


def _state(good: bool, before: CheckState, changed: bool) -> CheckState:
    """Куда идёт дом: негоден — в REJECTED; правка (или прежняя правка) — EDITED; иначе GOOD."""
    if not good:
        return CheckState.REJECTED
    return CheckState.EDITED if changed or before is CheckState.EDITED else CheckState.GOOD


def _changed(file: Path, edit: markup_edit.Edit) -> manual.Markup | None:
    """Разметка после правки, если она отличается от записанной; такая же — None."""
    old = manual.read(file)
    new = _edited(old, edit)
    return None if new == old else new


def _save(editor, folder: Path, file: Path, m: manual.Markup) -> None:
    orig = folder / editor.original_dir / file.name
    if not orig.exists():  # автоматика остаётся как была: по ней считают, сколько хозяин поправил
        orig.parent.mkdir(exist_ok=True)
        shutil.copyfile(file, orig)
    markup_toml.write(file, m)


def _assembly(cfg: Config, file: Path) -> dict:
    """Собирается ли записанная разметка в пример тем же кодом, что `genfacade manual`."""
    try:
        m = manual.read(file)
        manual.check_kinds(m, cfg)
        manual.house(m, cfg.data.manual)
    except (manual.BadMarkup, manual.Unsupported, tomllib.TOMLDecodeError, ValidationError) as e:
        return {"ok": False, "detail": str(e)}
    return {"ok": True, "detail": ""}
