"""Слепая проверка листов глазами (gf#268): эталон для метрики правдоподобия.

Папка — один вариант `genfacade realtest -o <папка>`: в `<режим>/<строка>/<дом>.json` листы строк
таблицы (модель, подмены, правило GenPlan), в `<режим>/reference/` — настоящие дома. На доме хозяин
видит настоящий лист и листы строк `[review] rows` (config/viewer.toml) в случайном порядке без
названий — места A, B, C; ставит «годен / нет» и причину. Порядок мест — от seed, режима и дома:
тот же при каждом открытии. Отметки — `<папка>/review.json`; чья строка на каком месте, страница
не знает, раскрывает только сводка (`genfacade review`). Строка может прийти из папки другого
режима (`blind/model-`), и настоящий дом можно поставить на место наравне со строками: тогда на
доме рядом ответы обоих режимов и настоящий, все вслепую (gf#272).
"""

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import numpy
from pydantic import BaseModel

from genfacade.config import Review
from genfacade.metrics import calibrate, realtest
from genfacade.schema import FacadeSheet, Mode, Refusal, Refused

MARKS = "review.json"
LOCK = "review.lock"  # запись отметок — по одной на папку, во всех процессах смотрелки


class Mark(BaseModel):
    """Отметка листа: годен ли он на вид как настоящий дом и почему нет."""

    ok: bool
    why: str = ""


class Missing(Refused):
    """Нет такого дома, места или папки строки; текст — что именно."""

    def __init__(self, detail: str):
        super().__init__(Refusal.NO_REVIEW_ITEM, detail)


def houses(root: Path) -> list[str]:
    """Дома, у которых есть настоящий лист, в обоих режимах — по первому режиму."""
    return sorted(p.stem for p in (root / Mode.WITH_OPENINGS / calibrate.REFERENCE).glob("*.json"))


def rows(root: Path, mode: Mode, cfg: Review) -> list[str]:
    """Папки строк для проверки: первая папка, чьё имя начинается с элемента `rows`, — в папке
    режима, а у элемента с режимом впереди (`blind/model-`) — в папке того режима; такая строка
    и записывается с режимом (`blind/model-run…`)."""
    out = []
    for entry in cfg.rows:
        other, _, prefix = entry.rpartition("/")
        folder = root / (Mode(other) if other else mode)
        found = sorted(d.name for d in folder.iterdir() if d.is_dir())
        match = next((name for name in found if name.startswith(prefix)), None)
        if match is None:
            raise Missing(f"в {folder} нет строки {prefix}…")
        out.append(f"{other}/{match}" if other else match)
    return out


def _folder(root: Path, mode: Mode, row: str) -> Path:
    """Папка строки: с режимом впереди — от корня, иначе — в папке режима (отметки gf#268
    записаны без режима)."""
    return root / row if "/" in row else root / mode / row


def slots(root: Path, mode: Mode, house: str, cfg: Review) -> list[str]:
    """Строки на местах A, B, C… дома: перемешаны от seed, режима и дома."""
    order = rows(root, mode, cfg)
    # hash() строки меняется от запуска к запуску — seed из sha256, порядок постоянный
    digest = hashlib.sha256(f"{cfg.seed}:{mode}:{house}".encode()).digest()
    rng = numpy.random.default_rng(int.from_bytes(digest[:8], "big"))
    return [order[i] for i in rng.permutation(len(order))]


def sheet(root: Path, mode: Mode, house: str, row: str) -> FacadeSheet | dict:
    """Лист строки дома или отказ модели — `Refused.record()` под `realtest.REFUSED`."""
    if house not in houses(root):
        raise Missing(f"нет дома {house!r}")
    path = _folder(root, mode, row) / f"{house}.json"
    if not path.exists():
        raise Missing(f"нет листа {path.relative_to(root)}")
    data = json.loads(path.read_text())
    return data[realtest.REFUSED] if realtest.REFUSED in data else FacadeSheet.model_validate(data)


def marks(root: Path) -> dict[str, dict]:
    path = root / MARKS
    return json.loads(path.read_text()) if path.exists() else {}


def key(mode: Mode, house: str, slot: int) -> str:
    return f"{mode}/{house}/{slot}"


def is_done(found: dict[str, dict], mode: Mode, house: str, places: int) -> bool:
    """Дом размечен: отметка есть на каждом из мест. Считает сервер — страница не собирает
    это состояние сама из отметок (чистый контур, C12)."""
    return all(key(mode, house, s) in found for s in range(places))


def save(root: Path, mode: Mode, house: str, slot: int, mark: Mark, cfg: Review) -> bool:
    """Отметка места дома; за местом в файле записана и строка — сводке не надо перемешивать.
    Возвращает, размечен ли теперь дом целиком."""
    if house not in houses(root):
        raise Missing(f"нет дома {house!r}")
    order = slots(root, mode, house, cfg)
    if not 0 <= slot < len(order):
        raise Missing(f"нет места {slot} у дома {house!r}")
    with locked(root):
        found = marks(root)
        found[key(mode, house, slot)] = {**mark.model_dump(), "row": order[slot],
                                         "date": date.today().isoformat()}
        tmp = root / f"{MARKS}.tmp"
        tmp.write_text(json.dumps(found, ensure_ascii=False, indent=2))
        os.replace(tmp, root / MARKS)
    return is_done(found, mode, house, len(order))


@contextmanager
def locked(root: Path, name: str = LOCK):
    """Отметки пишутся по одной: «Не годен» и причина уходят двумя запросами сразу, а на папку
    смотрят два сервера (локальный и наружный) — без блокировки записи перемешались и испортили
    файл (04.11, gf#272). Замена готовым файлом (`os.replace`): оборванная запись не оставит
    полфайла."""
    with (root / name).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def summary(root: Path, cfg: Review) -> str:
    """Доля принятых листов по строкам и режимам, Markdown; не размечено — в скобках."""
    found = marks(root)
    lines = ["| строка | режим | принято | размечено из |", "|---|---|---|---|"]
    for mode in cfg.modes:
        for row in rows(root, mode, cfg):
            got = [m for k, m in found.items() if k.startswith(f"{mode}/") and m["row"] == row]
            ok = sum(m["ok"] for m in got)
            share = f"{ok / len(got):.2f} ({ok}/{len(got)})" if got else "—"
            lines.append(f"| {row} | {mode} | {share} | {len(houses(root))} |")
    return "\n".join(lines)
