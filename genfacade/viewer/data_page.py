"""Страница «Данные» (gf#356, хозяин 08.11 и 09.11): на чём учим и проверяем — корпус синтетики,
дообучение на BuildingNet, реальный тест; у каждого набора плашка одной формы и список всех
примеров. Сервер считает числа и доли; страница рисует.

Опись источника (`store.load_manifest`) отвечает на «сколько»; доли формы, этажей, крыш и
материалов опись не хранит, поэтому они читаются из примеров — по `stats_sample` домов через равные
промежутки (config/viewer.toml, [data_view]) и запоминаются до новой сборки датасета.
"""

import json
import re
from collections import Counter
from pathlib import Path

from genfacade.config import Config
from genfacade.datasets import store
from genfacade.schema import DataAttr, PaletteRole, PlanShape, Source, Split

# Признаки считаются для корпуса, где они есть в каждом примере; у остальных наборов — опись.
SOURCES = (Source.SYNTHETIC, Source.BUILDINGNET, Source.MANUAL)  # по порядку обучения
SPLIT_HEAD = 512  # поле split стоит в начале файла примера: для списка читаем только начало
RECT_CORNERS = 4  # контур прямоугольного дома

_cache: dict[tuple[str, str], dict] = {}
_index_cache: dict[tuple[str, int], list[tuple[str, str]]] = {}
_SPLIT = re.compile(rb'"split":\s*"(\w+)"')


def overview(cfg: Config) -> dict:
    """Наборы по порядку обучения; у каждого плашка одной формы: что это, роль, что лежит,
    доли признаков, примеры. Чего в наборе нет — None (страница ставит прочерк)."""
    root, view = cfg.data.paths.samples_dir, cfg.viewer.data_view
    sets = [_card(cfg, source, found) for source in SOURCES if (found := store.ids(root, source))]
    return {"sets": sets, "attrs": {a.value: t for a, t in view.attrs.items()}}


def _card(cfg: Config, source: Source, found: list[str]) -> dict:
    view = cfg.viewer.data_view
    manifest = store.load_manifest(cfg.data.paths.samples_dir, source)
    elements = manifest.get("elements")
    label = view.sets[source]
    return {
        "source": source, **label.model_dump(), "role_title": view.roles[label.role],
        "samples": manifest.get("samples"), "walls": manifest.get("walls"),
        "blind_walls": manifest.get("blind_walls"), "splits": manifest.get("splits") or {},
        "elements": sum(elements.values()) if elements else None, "date": manifest.get("date"),
        "examples": _spread(found, view.examples), "shares": _shares(cfg, source, found),
        "rejected": manifest.get("reasons") if source is Source.BUILDINGNET else None,
        "origins": _origins(cfg, manifest, found) if source is Source.MANUAL else None,
    }


def listing(cfg: Config, source: Source, page: int, split: Split | None, query: str) -> dict:
    """Одна страница всех примеров набора с фильтром по разбиению и подстроке имени; страница
    за краем списка заменяется ближайшей."""
    size = cfg.viewer.data_view.page_size
    named = [(i, sp) for i, sp in _index(cfg, source) if query.lower() in i.lower()]
    shown = [(i, sp) for i, sp in named if split is None or sp == split]
    pages = max(1, -(-len(shown) // size))
    page = min(max(page, 1), pages)
    return {"source": source, "title": cfg.viewer.data_view.sets[source].title, "page": page,
            "pages": pages, "per_page": size, "total": len(shown),
            "splits": dict(Counter(sp for _, sp in named)),
            "items": [{"id": i, "split": sp} for i, sp in shown[(page - 1) * size:page * size]]}


def _index(cfg: Config, source: Source) -> list[tuple[str, str]]:
    """(имя, разбиение) всех примеров набора; кэш — до смены числа файлов."""
    root = cfg.data.paths.samples_dir
    found = store.ids(root, source)
    key = (str(root / source), len(found))
    if key not in _index_cache:
        _index_cache[key] = [(i, _split_of(store.path(root, source, i))) for i in found]
    return _index_cache[key]


def _split_of(file: Path) -> str:
    with file.open("rb") as f:
        found = _SPLIT.search(f.read(SPLIT_HEAD))
    return found.group(1).decode() if found else ""


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
    if attr is DataAttr.SHAPE:
        return cfg.viewer.data_view.shapes[PlanShape(value)]
    return table.get(attr, {}).get(value, value)


def _attrs(sample: dict) -> dict[DataAttr, str]:
    spec = sample["sheet"]["spec"]
    main = next(m for m in spec["materials"] if m["id"] == PaletteRole.MAIN)
    roof = spec["roof"]
    plan = sample.get("plan")
    shape = {} if plan is None else {DataAttr.SHAPE: _shape(plan)}
    return shape | {DataAttr.SIDES: str(len(sample["sheet"]["facades"])),
                    DataAttr.FLOORS: str(spec["floors"]),
                    DataAttr.ROOF: roof["kind"] if isinstance(roof, dict) else roof,
                    DataAttr.WALLS: main["kind"], DataAttr.STYLE: spec["style"]}


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


def _shape(plan: dict) -> str:
    rectangle = len(plan["outline"]) == RECT_CORNERS
    return PlanShape.RECTANGLE if rectangle else PlanShape.OTHER
