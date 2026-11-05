"""Перенос отказов старого вида в коды Refusal (gf#293), один раз на папку `outputs/`.

До gf#293 отказ был строкой: в meta.json прогона — «план отклонён: …» / «модель не ответила: …»,
в ответе модели realtest — `{"error": "…", "attempts": […]}`. Код по тексту выводится только
здесь, один раз; остальной код читает только `refusal` с кодом. Удалить вместе с закрытием gf#293.

    python3 tools/migrate_refusals.py outputs
"""

import json
import sys
from pathlib import Path

from genfacade.metrics import realtest
from genfacade.schema import Refusal, refusal_record

OLD_META = {"план отклонён: ": Refusal.PLAN_REJECTED, "модель не ответила: ": None}
MODEL_STARTS = {  # начало текста ModelError до gf#293 → код
    "за ": Refusal.MODEL_NO_ANSWER,
    "стаб знает": Refusal.HOUSE_OUT_OF_MODEL,
    "дом не записывается": Refusal.HOUSE_OUT_OF_MODEL,
    "условие дома": Refusal.HOUSE_OUT_OF_MODEL,
    "словарь": Refusal.MODEL_MISMATCH,
    "нет чекпойнта": Refusal.MODEL_MISSING,
}


def model_code(text: str) -> Refusal:
    found = [code for start, code in MODEL_STARTS.items() if text.startswith(start)]
    if len(found) != 1:
        raise SystemExit(f"не узнан отказ модели: {text!r}")
    return found[0]


def meta_record(text: str) -> dict:
    for start, code in OLD_META.items():
        if text.startswith(start):
            detail = text.removeprefix(start)
            return refusal_record(code or model_code(detail), detail)
    raise SystemExit(f"не узнан отказ прогона: {text!r}")


def migrate(root: Path) -> tuple[int, int]:
    metas = answers = 0
    for path in root.rglob("*.json"):
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            continue
        if path.name == "meta.json" and isinstance(data.get("refusal"), str):
            data["refusal"] = meta_record(data["refusal"])
            metas += 1
        elif set(data) == {"error", "attempts"}:  # так писал только realtest
            data = {realtest.REFUSED: refusal_record(model_code(data["error"]), data["error"]),
                    "attempts": data["attempts"]}
            answers += 1
        else:
            continue
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return metas, answers


if __name__ == "__main__":
    metas, answers = migrate(Path(sys.argv[1]))
    print(f"meta.json: {metas}, ответов модели: {answers}")
