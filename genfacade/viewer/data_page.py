"""Страница «Данные» (gf#356, хозяин 08.11): датасет, на котором учим, — корпус синтетики, набор
для дообучения (BuildingNet) и реальный тест. Сервер считает числа и доли; страница рисует.

Опись источника (`store.load_manifest`) отвечает на «сколько»; доли формы, этажей, крыш и
материалов опись не хранит, поэтому они читаются из примеров — по `stats_sample` домов через равные
промежутки (config/viewer.toml, [data_view]) и запоминаются до новой сборки датасета.
"""

import json
from collections import Counter

from genfacade.config import Config
from genfacade.datasets import store
from genfacade.schema import DataAttr, PaletteRole, Source

# Признаки считаются для корпуса, где они есть в каждом примере; у остальных наборов — опись.
CORPUS = Source.SYNTHETIC
FINETUNE = Source.BUILDINGNET
REAL_TEST = Source.MANUAL

_cache: dict[tuple[str, str], dict] = {}


def overview(cfg: Config) -> dict:
    """Наборы по порядку обучения: опись, примеры; у корпуса — ещё доли признаков, у теста —
    дома по источникам разметки."""
    root, view = cfg.data.paths.samples_dir, cfg.viewer.data_view
    sets = []
    for source in (CORPUS, FINETUNE, REAL_TEST):
        found = store.ids(root, source)
        if not found:
            continue
        manifest = store.load_manifest(root, source)
        sets.append({
            "source": source, **view.sets[source].model_dump(),
            "samples": manifest["samples"], "walls": manifest["walls"],
            "blind_walls": manifest["blind_walls"], "splits": manifest["splits"],
            "elements": manifest["elements"], "date": manifest["date"],
            "examples": _spread(found, view.examples),
            "shares": _shares(cfg, source, found) if source is CORPUS else None,
            "rejected": _reasons(manifest) if source is FINETUNE else None,
            "origins": _origins(cfg, manifest, found) if source is REAL_TEST else None,
        })
    return {"sets": sets, "attrs": {a.value: t for a, t in view.attrs.items()}}


def _spread[T](items: list[T], n: int) -> list[T]:
    """n элементов через равные промежутки: по первым n видны бы одни соседи."""
    if len(items) <= n:
        return items
    return [items[i * len(items) // n] for i in range(n)]


def _shares(cfg: Config, source: Source, ids: list[str]) -> dict:
    """Доли признаков по выборке домов; ключ кэша — опись: новая сборка датасета считает заново.
    Подписи значений ставит сервер (labels в viewer.toml): страница признаков не знает."""
    root, n = cfg.data.paths.samples_dir, cfg.viewer.data_view.stats_sample
    key = (str(root / source), store.load_manifest(root, source)["date"])
    if key not in _cache:
        counts = {a: Counter() for a in DataAttr}
        picked = _spread(ids, n)
        for i in picked:
            for attr, value in _attrs(json.loads(store.path(root, source, i).read_text())).items():
                counts[attr][value] += 1
        _cache[key] = {"of": len(picked), "attrs": {a.value: [
            {"label": _label(a, v, cfg), "n": k, "share": k / len(picked)}
            for v, k in c.most_common()] for a, c in counts.items()}}
    return _cache[key]


def _label(attr: DataAttr, value: str, cfg: Config) -> str:
    """Подпись значения признака: roof, walls, style — из labels; нет подписи — само значение."""
    labels = cfg.viewer.labels
    table = {DataAttr.ROOF: labels.roof, DataAttr.WALLS: labels.kind, DataAttr.STYLE: labels.style}
    return table.get(attr, {}).get(value, value)


def _attrs(sample: dict) -> dict[DataAttr, str]:
    spec = sample["sheet"]["spec"]
    main = next(m for m in spec["materials"] if m["id"] == PaletteRole.MAIN)
    roof = spec["roof"]
    return {DataAttr.SIDES: str(len(sample["sheet"]["facades"])),
            DataAttr.FLOORS: str(spec["floors"]),
            DataAttr.ROOF: roof["kind"] if isinstance(roof, dict) else roof,
            DataAttr.WALLS: main["kind"], DataAttr.STYLE: spec["style"]}


def _reasons(manifest: dict) -> dict[str, int]:
    """Почему дома BuildingNet не вошли в набор: причина → сколько."""
    return manifest.get("reasons", {})


def _origins(cfg: Config, manifest: dict, built: list[str]) -> list[dict]:
    """Дома теста по источникам разметки: сколько размечено, сколько собрано, сколько ждёт."""
    folder = cfg.data.manual.paths.markup_dir
    waiting = set(manifest.get("waiting", {}))
    result = []
    for source in sorted(p for p in folder.iterdir() if p.is_dir()) if folder.exists() else []:
        names = sorted(p.stem for p in source.glob("*.toml"))
        result.append({"name": source.name, "marked": len(names),
                       "built": sum(n in built for n in names),
                       "waiting": sum(n in waiting for n in names)})
    return result
