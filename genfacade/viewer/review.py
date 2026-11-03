"""Слепая проверка листов глазами (gf#268): эталон для метрики правдоподобия.

Папка — один вариант `genfacade realtest -o <папка>`: в `<режим>/<строка>/<дом>.json` листы строк
таблицы (модель, подмены, правило GenPlan), в `<режим>/reference/` — настоящие дома. На доме хозяин
видит настоящий лист и листы строк `[review] rows` (config/viewer.toml) в случайном порядке без
названий — места A, B, C; ставит «годен / нет» и причину. Порядок мест — от seed, режима и дома:
тот же при каждом открытии. Отметки — `<папка>/review.json`; чья строка на каком месте, страница
не знает, раскрывает только сводка (`genfacade review`).
"""

import hashlib
import json
from datetime import date
from pathlib import Path

import numpy
from pydantic import BaseModel

from genfacade.config import Review
from genfacade.metrics import calibrate, realtest
from genfacade.schema import FacadeSheet, Mode

MARKS = "review.json"


class Mark(BaseModel):
    """Отметка листа: годен ли он на вид как настоящий дом и почему нет."""

    ok: bool
    why: str = ""


class Missing(LookupError):
    """Нет такого дома, места или папки строки; текст — что именно."""


def houses(root: Path) -> list[str]:
    """Дома, у которых есть настоящий лист, в обоих режимах — по первому режиму."""
    return sorted(p.stem for p in (root / Mode.WITH_OPENINGS / calibrate.REFERENCE).glob("*.json"))


def rows(root: Path, mode: Mode, cfg: Review) -> list[str]:
    """Папки строк для проверки: первая папка режима, чьё имя начинается с элемента `rows`."""
    found = sorted(d.name for d in (root / mode).iterdir() if d.is_dir())
    out = []
    for prefix in cfg.rows:
        match = next((name for name in found if name.startswith(prefix)), None)
        if match is None:
            raise Missing(f"в {root / mode} нет строки {prefix}…")
        out.append(match)
    return out


def slots(root: Path, mode: Mode, house: str, cfg: Review) -> list[str]:
    """Строки на местах A, B, C… дома: перемешаны от seed, режима и дома."""
    order = rows(root, mode, cfg)
    # hash() строки меняется от запуска к запуску — seed из sha256, порядок постоянный
    digest = hashlib.sha256(f"{cfg.seed}:{mode}:{house}".encode()).digest()
    rng = numpy.random.default_rng(int.from_bytes(digest[:8], "big"))
    return [order[i] for i in rng.permutation(len(order))]


def sheet(root: Path, mode: Mode, house: str, row: str) -> FacadeSheet | str:
    """Лист строки дома или текст отказа (`{"error": …}` в ответах модели)."""
    if house not in houses(root):
        raise Missing(f"нет дома {house!r}")
    path = root / mode / row / f"{house}.json"
    if not path.exists():
        raise Missing(f"нет листа {mode}/{row}/{house}")
    data = json.loads(path.read_text())
    return data[realtest.REFUSED] if realtest.REFUSED in data else FacadeSheet.model_validate(data)


def marks(root: Path) -> dict[str, dict]:
    path = root / MARKS
    return json.loads(path.read_text()) if path.exists() else {}


def key(mode: Mode, house: str, slot: int) -> str:
    return f"{mode}/{house}/{slot}"


def save(root: Path, mode: Mode, house: str, slot: int, mark: Mark, cfg: Review) -> None:
    """Отметка места дома; за местом в файле записана и строка — сводке не надо перемешивать."""
    order = slots(root, mode, house, cfg)
    if not 0 <= slot < len(order):
        raise Missing(f"нет места {slot} у дома {house!r}")
    found = marks(root)
    found[key(mode, house, slot)] = {**mark.model_dump(), "row": order[slot],
                                     "date": date.today().isoformat()}
    (root / MARKS).write_text(json.dumps(found, ensure_ascii=False, indent=2))


def summary(root: Path, cfg: Review) -> str:
    """Доля принятых листов по строкам и режимам, Markdown; не размечено — в скобках."""
    found = marks(root)
    lines = ["| строка | режим | принято | размечено из |", "|---|---|---|---|"]
    for mode in Mode:
        for row in rows(root, mode, cfg):
            got = [m for k, m in found.items() if k.startswith(f"{mode}/") and m["row"] == row]
            ok = sum(m["ok"] for m in got)
            share = f"{ok / len(got):.2f} ({ok}/{len(got)})" if got else "—"
            lines.append(f"| {row} | {mode} | {share} | {len(houses(root))} |")
    return "\n".join(lines)
