"""Сборка коттеджей BuildingNet в примеры (`data: Разбиение без утечек`: часть — по
официальному разбиению train / val / test, gf#198).

Дом, который не извлечён, не пишется: причина — в описи (`rejected`), как и ошибки валидатора
у извлечённых (`invalid`) — по ним видно, что чинить в извлечении (датчик gf#154).
"""

from collections import Counter
from pathlib import Path

from genfacade.config import Config
from genfacade.datasets import store
from genfacade.datasets.buildingnet import extract, mesh
from genfacade.schema import Source, Split
from genfacade.validate import errors, validate


def models(cfg: Config, splits: tuple[Split, ...] = (Split.TEST,)) -> list[tuple[str, Split]]:
    """Коттеджи частей splits: имена моделей с префиксом категории из настроек и их часть."""
    rules = cfg.data.buildingnet
    return [(n, split) for split in splits for n in rules.paths.splits[split].read_text().split()
            if n.startswith(tuple(rules.categories))]


def run(cfg: Config, count: int = 0, splits: tuple[Split, ...] = (Split.TEST,)) -> Path:
    """Первые count коттеджей частей splits (0 — все) → примеры и опись с отказами."""
    rules, root = cfg.data.buildingnet, cfg.data.paths.samples_dir
    rejected, invalid = {}, Counter()
    # Источник целиком — производное этой сборки: дом, отброшенный новой версией извлечения,
    # не должен остаться от прошлой.
    for old in store.ids(root, Source.BUILDINGNET):
        store.path(root, Source.BUILDINGNET, old).unlink()
    for name, split in models(cfg, splits)[:count or None]:
        parts = mesh.read(rules.paths.models_dir / f"{name}.obj",
                          mesh.labels(rules.paths.component_labels, name))
        try:
            sample = extract.house(name, parts, rules, split)
        except extract.Rejected as e:
            rejected[name] = str(e)
            continue
        invalid.update(v.rule for v in errors(validate(sample.sheet, cfg.checks)))
        store.write(sample, root)
    return store.write_manifest(root, Source.BUILDINGNET, {
        "rejected": rejected,
        "reasons": dict(Counter(r.split(":")[0] for r in rejected.values())),
        "invalid": dict(invalid)})
