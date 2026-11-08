"""Очередь проверки домов на странице правки разметки (gf#348): состояние и время на дом.

Состояние дома — хранимое поле `state` в файле очереди, а не вывод из наличия файла разметки
(docs/clean-contour.md, п. 1): каждый дом папки при чтении получает запись `unchecked`. Пишет её
одна функция — `transition`, по таблице TRANSITIONS; остальное (`open_house`, `decide`) вызывает
её. Время на дом — секунды от последнего открытия до решения, их считает сервер.
"""

import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError, model_validator

from genfacade.config import MarkupEditor
from genfacade.schema import CheckState, Model, Refusal, Refused, RejectReason
from genfacade.viewer import review

LOCK = "check.lock"

# Что можно решить о доме, которого уже коснулись. Принятый дом поправляют и после («хорошо» →
# правка); поправленный остаётся поправленным, пока его не признали негодным: правка уже в файле.
TRANSITIONS: dict[CheckState, set[CheckState]] = {
    CheckState.UNCHECKED: {CheckState.GOOD, CheckState.EDITED, CheckState.REJECTED},
    CheckState.GOOD: {CheckState.GOOD, CheckState.EDITED, CheckState.REJECTED},
    CheckState.EDITED: {CheckState.EDITED, CheckState.REJECTED},
    CheckState.REJECTED: {CheckState.GOOD, CheckState.EDITED, CheckState.REJECTED},
}


class Record(Model):
    """Запись дома в файле очереди. Умолчания объявлены здесь, при чтении не подставляются."""

    state: CheckState = CheckState.UNCHECKED
    reason: RejectReason | None = None   # только у негодного
    note: str = ""
    opened_at: float | None = None       # unix-время последнего открытия
    decided_at: str | None = None        # когда принято решение, ISO UTC
    seconds: float | None = None         # от открытия до решения

    @model_validator(mode="after")
    def _reason_only_when_rejected(self) -> "Record":
        if (self.state is CheckState.REJECTED) != (self.reason is not None):
            raise ValueError(f"состояние {self.state} и причина {self.reason} не сходятся")
        return self


def path(cfg: MarkupEditor, folder: Path) -> Path:
    return folder / cfg.state_file


def houses(folder: Path) -> list[str]:
    """Дома очереди — файлы разметки папки по имени; имя файла = id дома."""
    return sorted(p.stem for p in folder.glob("*.toml"))


def read(cfg: MarkupEditor, folder: Path) -> dict[str, Record]:
    """Записи файла очереди; файл, который не читается, — отказ с причиной, а не пустая очередь."""
    file = path(cfg, folder)
    if not file.exists():
        return {}
    try:
        raw = json.loads(file.read_text())["houses"]
        return {k: Record.model_validate(v) for k, v in raw.items()}
    except (ValueError, KeyError, TypeError, ValidationError) as e:
        raise Refused(Refusal.BAD_CHECK_STATE, f"{file}: {e}") from e


def _write(cfg: MarkupEditor, folder: Path, found: dict[str, Record]) -> None:
    file = path(cfg, folder)
    tmp = file.with_suffix(".json.tmp")
    body = {"houses": {k: v.model_dump(mode="json") for k, v in sorted(found.items())}}
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2))
    os.replace(tmp, file)


def _update(cfg: MarkupEditor, folder: Path, house: str, change) -> Record:
    """Запись дома под замком: новые дома папки получают `unchecked`, `change` — запись дома."""
    with review.locked(folder, LOCK):
        found = read(cfg, folder)
        for name in houses(folder):
            found.setdefault(name, Record())
        found[house] = change(found[house])
        _write(cfg, folder, found)
        return found[house]


def sync(cfg: MarkupEditor, folder: Path) -> dict[str, Record]:
    """Записи всех домов папки; новому дому запись `unchecked` пишется сразу."""
    with review.locked(folder, LOCK):
        found = read(cfg, folder)
        names = houses(folder)
        if any(n not in found for n in names):
            for n in names:
                found.setdefault(n, Record())
            _write(cfg, folder, found)
    return {n: found[n] for n in names}


def transition(rec: Record, new: CheckState, reason: RejectReason | None, note: str,
               now: float) -> Record:
    """Единственное место, где меняется `state`; перехода нет в таблице — отказ."""
    if new not in TRANSITIONS[rec.state]:
        raise Refused(Refusal.BAD_CHECK_STEP, f"{rec.state} → {new}")
    seconds = None if rec.opened_at is None else round(now - rec.opened_at, 1)
    return Record(state=new, reason=reason, note=note, opened_at=rec.opened_at, seconds=seconds,
                  decided_at=datetime.fromtimestamp(now, UTC).isoformat(timespec="seconds"))


def open_house(cfg: MarkupEditor, folder: Path, house: str) -> Record:
    """Дом открыт: отсчёт времени на дом идёт от этого момента."""
    return _update(cfg, folder, house, lambda r: r.model_copy(update={"opened_at": time.time()}))


def decide(cfg: MarkupEditor, folder: Path, house: str,
           verdict: tuple[CheckState, RejectReason | None, str]) -> Record:
    new, reason, note = verdict
    return _update(cfg, folder, house, lambda r: transition(r, new, reason, note, time.time()))


def counts(found: dict[str, Record]) -> dict:
    """Проверено / осталось и медиана секунд на дом по решённым — для строки прогресса."""
    seconds = [r.seconds for r in found.values()
               if r.state is not CheckState.UNCHECKED and r.seconds is not None]
    checked = sum(r.state is not CheckState.UNCHECKED for r in found.values())
    return {"total": len(found), "checked": checked, "left": len(found) - checked,
            "median_seconds": statistics.median(seconds) if seconds else None}


def next_unchecked(found: dict[str, Record], after: str | None = None) -> str | None:
    """Следующий непроверенный дом после `after` по кругу; None — проверены все."""
    names = sorted(found)
    start = names.index(after) + 1 if after in found else 0
    for name in names[start:] + names[:start]:
        if found[name].state is CheckState.UNCHECKED:
            return name
    return None
