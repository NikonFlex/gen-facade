"""Конвейер и его трасса: выход каждого шага — в папку прогона (generation.md, п. 10).

Смотрелка и `genfacade render` читают одно и то же: папку прогона с `meta.json`,
где перечислены шаги и файлы. Шаги, которых ещё нет в коде, идут с `file = None`.
"""

import json
import re
import subprocess  # noqa: S404 — только git rev-parse
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from genfacade.config import Config
from genfacade.render.preview import to_png
from genfacade.render.svg import sheet_svg
from genfacade.schema import FacadeSheet
from genfacade.unfold import unfold

# Семь шагов схемы (docs/assets/facade-modules.png); седьмой — позже, вместе с Егором.
STEPS = {1: "Параметры дома", 2: "План", 3: "Развёртка", 4: "Раскладка стен",
         5: "Сетка и проверка", 6: "Лист фасадов"}
INPUT, UNFOLD, SHEET, SHEET_JSON, PREVIEW, META = (
    "input.json", "03_unfold.svg", "06_sheet.svg", "sheet.json", "preview.png", "meta.json")
RUN_ID = re.compile(r"^[\w.-]+$")  # имя папки прогона: без / и .., чтобы не выйти из runs_dir


def new_run_dir(runs_dir: Path, name: str) -> Path:
    """Свободная папка <время>-<имя>; два запуска в одну секунду получают суффикс."""
    base = f"{datetime.now():%Y%m%d-%H%M%S}-{re.sub(r'[^\w.-]', '_', name)}"
    out, n = runs_dir / base, 2
    while out.exists():
        out, n = runs_dir / f"{base}-{n}", n + 1
    return out


def run(house: FacadeSheet, out: Path, cfg: Config, source: str) -> Path:
    """Шаги этапа 0 — развёртка и лист — с трассой в out; source — откуда дом."""
    out.mkdir(parents=True, exist_ok=True)
    (out / INPUT).write_text(house.model_dump_json(indent=2, exclude_none=True))
    sheet = unfold(house, cfg.library.roof.thickness_m)
    bare = [f.model_copy(update={"elements": [], "zones": []}) for f in sheet.facades]
    (out / UNFOLD).write_text(sheet_svg(sheet.model_copy(update={"facades": bare}), cfg))
    (out / SHEET).write_text(sheet_svg(sheet, cfg))
    (out / SHEET_JSON).write_text(sheet.model_dump_json(indent=2))
    has_png = to_png(out / SHEET, out / PREVIEW, cfg.sheet.preview.width_px)
    files = {3: UNFOLD, 6: SHEET}
    meta = {
        "source": source, "date": datetime.now().isoformat(timespec="seconds"),
        "git_sha": _git_sha(), "genfacade": version("genfacade"),
        "input": INPUT, "sheet_json": SHEET_JSON, "preview": PREVIEW if has_png else None,
        "steps": [{"n": n, "title": t, "file": files.get(n)} for n, t in STEPS.items()],
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
