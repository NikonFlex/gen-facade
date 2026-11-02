"""Сводка устойчивости модели по вариантам сэмплинга (gf#257): один и тот же реальный тест
несколько раз — с разными seed, temperature, top_k, best_of — и числа рядом.

    <root>/<вариант>/<режим>/rows/metrics.json   `genfacade realtest -o <root>/<вариант>`
    <root>/summary.md                            эта сводка

Вариант — пары `ключ=значение` настроек `[layout]` (config/models.toml), в имени папки через
запятую: `temperature=0.8,seed=0` (tools/retrain.sh, этап stability). Числа берутся из
metrics.json строк, а не из summary.md каждого варианта. Разброс по сидам — по вариантам, которые
отличаются только seed: среднее ± стандартное отклонение (выборочное, n − 1).
"""

import re
import statistics
from pathlib import Path

from genfacade.config import Config
from genfacade.metrics import realtest
from genfacade.schema import Mode

SUMMARY = "summary.md"
SEED = "seed"             # ключ [layout]: по нему считается разброс
PAIRS = ","               # пары варианта в имени папки
EMPTY = "—"               # числа нет: метрика не посчитана или вариант один


def run(root: Path, cfg: Config) -> Path:
    """Папки вариантов root → root/summary.md; нет ни одного варианта — FileNotFoundError."""
    variants = _variants(root)
    if not variants:
        raise FileNotFoundError(f"в {root} нет вариантов: ждали "
                                "<вариант>/<режим>/rows/metrics.json")
    parts = [f"# Устойчивость по вариантам сэмплинга\n\nВарианты: {', '.join(variants)}.\n"]
    for mode in Mode:
        rows = {v: dict(realtest.named_rows(root / v, mode)) for v in variants}
        parts += [f"## {mode}\n", _by_variant(rows, cfg), _by_seed(rows, cfg)]
    (root / SUMMARY).write_text("\n".join(parts))
    return root / SUMMARY


def _variants(root: Path) -> list[str]:
    """Папки вариантов по порядку чисел в имени: seed=2 раньше seed=10."""
    found = [d.name for d in root.iterdir() if (d / Mode.BLIND / "rows").is_dir()]
    return sorted(found, key=lambda n: [int(t) if t.isdigit() else t
                                        for t in re.split(r"(\d+)", n)])


def _pairs(variant: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in variant.split(PAIRS))


def _table(header: list[str], body: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(r) + " |" for r in body]) + "\n"


def _number(value: float | None, cfg: Config) -> str:
    return EMPTY if value is None else f"{value:.{cfg.metrics.realtest.digits}f}"


def _by_variant(rows: dict[str, dict[str, dict]], cfg: Config) -> str:
    """Строка таблицы на (строку, вариант): годных и колонки `[realtest] stability`."""
    columns = cfg.metrics.realtest.stability
    body = [[name, variant, realtest.good(row), *(_number(row[c], cfg) for c in columns)]
            for name in _names(rows) for variant, by_name in rows.items()
            if (row := by_name.get(name)) is not None]
    return "### По вариантам\n\n" + _table(["строка", "вариант", realtest.GOOD, *columns], body)


def _names(rows: dict[str, dict[str, dict]]) -> list[str]:
    """Имена строк в порядке первого варианта (в нём строки идут как в summary.md)."""
    return list(next(iter(rows.values())))


def _by_seed(rows: dict[str, dict[str, dict]], cfg: Config) -> str:
    """Среднее ± стандартное отклонение по вариантам, отличающимся только seed."""
    seeds = [v for v in rows if set(_pairs(v)) == {SEED}]
    title = f"### Разброс по seed (n = {len(seeds)}: {', '.join(seeds)})\n\n"
    if len(seeds) < 2:
        return title + "Меньше двух вариантов, отличающихся только seed, — разброса нет.\n"
    columns = cfg.metrics.realtest.stability
    body = [[name, *_spread([rows[v][name] for v in seeds], columns, cfg)]
            for name in _names(rows)]
    return title + _table(["строка", f"{realtest.GOOD} (доля)", *columns], body)


def _spread(group: list[dict], columns: list[str], cfg: Config) -> list[str]:
    """Ячейки строки по группе вариантов: годных (долей от числа домов) и колонки."""
    shares = [realtest.good_count(r) / r["count"] for r in group]
    return [_mean_sd(shares, cfg), *(_mean_sd([r[c] for r in group], cfg) for c in columns)]


def _mean_sd(values: list[float | None], cfg: Config) -> str:
    """«среднее ± sd» по посчитанным значениям; одно значение — без разброса."""
    known = [v for v in values if v is not None]
    if not known:
        return EMPTY
    sd = statistics.stdev(known) if len(known) > 1 else None
    return f"{_number(statistics.fmean(known), cfg)} ± {_number(sd, cfg)}"
