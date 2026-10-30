"""Чтение выпуска ResPlan: пикл со слоями shapely и каноническое разбиение split.json.

Выпуск — github.com/m-agour/ResPlan, ResPlan.zip (данные CC BY 4.0, LICENSE репозитория). Свой
загрузчик у ResPlan — голый `pickle.load` (README, «Quick start»), а pickle исполняет код при
загрузке. Поэтому распаковщик пускает только три глобала, которые есть в выпуске 28.07.2026
(перечислены pickletools 30.10.2026): любой другой — отказ до исполнения.
"""

import json
import pickle  # noqa: S403 — только с распаковщиком _OnlyGeometry ниже
from pathlib import Path

from genfacade.schema import Split

ALLOWED = frozenset({
    ("shapely.io", "from_wkb"),                # геометрия слоёв
    ("numpy._core.multiarray", "scalar"),      # net_area — число numpy
    ("numpy", "dtype"),
})
AUGMENTED = "augmented"  # ключ split.json: повороты и отражения других планов, не новые дома


class _OnlyGeometry(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if (module, name) not in ALLOWED:
            raise pickle.UnpicklingError(f"в пикле ResPlan запрещённый объект {module}.{name}")
        return super().find_class(module, name)


def plans(path: Path) -> list[dict]:
    """Планы выпуска: словарь слоёв на план (wall, window, door, front_door, inner, …)."""
    with path.open("rb") as f:
        return _OnlyGeometry(f).load()  # noqa: S301 — глобалы ограничены ALLOWED


def splits(path: Path) -> dict[int, Split]:
    """id плана → часть канонического разбиения; аугментированных копий здесь нет."""
    raw = json.loads(path.read_text())
    return {i: Split(part) for part, members in raw.items() if part != AUGMENTED
            for i in members}
