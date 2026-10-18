"""Сборка коттеджей официального теста BuildingNet в примеры (`data: Разбиение без утечек`:
часть — по официальному разбиению, у нас пока только test).

Дом, который не извлечён, не пишется: причина — в описи (`rejected`), как и ошибки валидатора
у извлечённых (`invalid`) — по ним видно, что чинить в извлечении (датчик gf#154).
"""

from collections import Counter
from pathlib import Path

from genfacade.config import Config
from genfacade.datasets import store
from genfacade.datasets.buildingnet import extract, mesh
from genfacade.schema import Source
from genfacade.validate import errors, validate


def models(cfg: Config) -> list[str]:
    """Коттеджи теста: имена моделей с префиксом категории из настроек."""
    rules = cfg.data.buildingnet
    names = rules.paths.test_split.read_text().split()
    return [n for n in names if n.startswith(tuple(rules.categories))]


def run(cfg: Config, count: int = 0) -> Path:
    """Первые count коттеджей теста (0 — все) → примеры и опись с отказами."""
    rules, root = cfg.data.buildingnet, cfg.data.paths.samples_dir
    rejected, invalid = {}, Counter()
    # Источник целиком — производное этой сборки: дом, отброшенный новой версией извлечения,
    # не должен остаться от прошлой.
    for old in store.ids(root, Source.BUILDINGNET):
        store.path(root, Source.BUILDINGNET, old).unlink()
    for name in models(cfg)[:count or None]:
        parts = mesh.read(rules.paths.models_dir / f"{name}.obj",
                          mesh.labels(rules.paths.component_labels, name))
        try:
            sample = extract.house(name, parts, rules)
        except extract.Rejected as e:
            rejected[name] = str(e)
            continue
        invalid.update(v.rule for v in errors(validate(sample.sheet, cfg.checks)))
        store.write(sample, root)
    return store.write_manifest(root, Source.BUILDINGNET, {
        "rejected": rejected,
        "reasons": dict(Counter(r.split(":")[0] for r in rejected.values())),
        "invalid": dict(invalid)})
