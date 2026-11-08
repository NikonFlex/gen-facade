"""Страница «Дома» смотрелки (gf#356): прогон карточкой — что показать и по чему фильтровать.

Итог, этажи, крыша, стены и число сторон считает сервер по файлам прогона; страница рисует и
фильтрует по ответу и своих правил не держит (docs/clean-contour.md, п. 13).
"""

import json
from pathlib import Path

from genfacade import pipeline
from genfacade.config import Config
from genfacade.schema import FacadeSheet, HouseSpec, PaletteRole, RunOutcome


def card(folder: Path, meta: dict, cfg: Config) -> dict:
    """Карточка прогона из meta.json и листа (или параметров шага 1, если до листа не дошли)."""
    request = meta.get("request")  # нет — лист собран вручную, без конвейера (просмотр эталона)
    layout = meta.get("layout")    # нет — прогон остановлен до шага 4
    return {
        "id": folder.name, "date": meta["date"], "thumb": _thumb(folder.name, meta),
        "source": meta["source"], "text": request["text"] if request else None,
        "mode": request["mode"] if request else None,
        "model": _model_name(layout["model"]) if layout else None,
        "outcome": outcome(meta), "errors": meta.get("errors"), "warnings": meta.get("warnings"),
        "refusal": meta.get("refusal"),
        "house": _house(folder, meta, cfg),
    }


def _thumb(run_id: str, meta: dict) -> str | None:
    """Картинка карточки: PNG листа; его нет (PNG не собрался — pipeline.finish, или папку
    собрали руками) — лист, нарисованный сервером по sheet.json; нет и листа — None."""
    if meta.get("preview"):
        return f"/files/{run_id}/{meta['preview']}"
    return f"/api/runs/{run_id}/sheet.svg" if meta.get("sheet_json") else None


def outcome(meta: dict) -> RunOutcome:
    """Итог прогона: отказ, ошибки валидатора, без них; шага 5 не было — не проверен."""
    if meta.get("refusal"):
        return RunOutcome.REFUSED
    if "errors" not in meta:
        return RunOutcome.UNCHECKED
    return RunOutcome.DEFECT if meta["errors"] else RunOutcome.CLEAN


def _model_name(model: str) -> str:
    """Модель шага 4 коротко: у чекпойнта — папка (`model/pretrain/model.pt` → pretrain), у
    стаба — его имя из трассы."""
    return Path(model).parent.name or model


def _house(folder: Path, meta: dict, cfg: Config) -> dict | None:
    """Этажи, крыша, стены и стороны — по листу; листа нет — по шагу 1 (стороны неизвестны);
    нет и шага 1 — None."""
    if meta.get("sheet_json"):
        sheet = FacadeSheet.model_validate_json((folder / meta["sheet_json"]).read_text())
        return _spec_facts(sheet.spec, cfg) | {"sides": len(sheet.facades)}
    spec_file = folder / pipeline.SPEC
    if spec_file.exists():
        spec = HouseSpec.model_validate(json.loads(spec_file.read_text())["spec"])
        return _spec_facts(spec, cfg) | {"sides": None}
    return None


def _spec_facts(spec: HouseSpec, cfg: Config) -> dict:
    main = next(m for m in spec.materials if m.id == PaletteRole.MAIN)
    return {"floors": spec.floors, "roof": spec.roof.kind, "walls": main.kind,
            "color": main.color or cfg.library.kinds.get(main.kind)}
