"""Кривая потерь обучения: loss.png и рядом loss.json с теми же числами (gf#106)."""

import json
from pathlib import Path

# matplotlib — в группе [train]: без обучения пакет его не тянет; Agg — рисовать без экрана.
import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot  # noqa: E402 — после выбора Agg

LOSS = "loss"
CURVES = {"train": "train", "val": "val"}  # ключ истории эпох → подпись на графике


def losses(history: list[dict], out: Path) -> Path:
    """Потери на токенах ответа по эпохам; цвета — по умолчанию matplotlib."""
    epochs = [h["epoch"] for h in history]
    fig, ax = pyplot.subplots()
    for key, label in CURVES.items():
        ax.plot(epochs, [h[key] for h in history], marker="o", label=label)
    ax.set_xticks(epochs)
    ax.set_xlabel("эпоха (train — среднее за эпоху, val — после неё)")
    ax.set_ylabel("cross-entropy на токенах ответа")
    ax.grid(True)
    ax.legend()
    path = out / f"{LOSS}.png"
    fig.savefig(path, bbox_inches="tight")
    pyplot.close(fig)
    (out / f"{LOSS}.json").write_text(json.dumps(
        {key: [h[key] for h in history] for key in ["epoch", *CURVES]}, indent=2))
    return path
