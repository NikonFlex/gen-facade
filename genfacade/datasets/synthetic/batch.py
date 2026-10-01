"""Сборка синтетики пачкой: дома по seed подряд → примеры и опись (specs/data.md, правило 10).

Сборку можно оборвать и запустить снова: готовые дома пропускаются. Чем собрано — в файле
`_build.json` рядом с примерами: настройки генератора и отброшенные дома. Дом с ошибкой
валидатора в датасет не пишется.
"""

import json
from pathlib import Path

from genfacade.config import Config
from genfacade.datasets import store
from genfacade.datasets.synthetic import build
from genfacade.pipeline import git_sha
from genfacade.schema import Source
from genfacade.validate import errors, validate

BUILD = "_build.json"


class BuildError(ValueError):
    """Сборку нельзя продолжить; текст — причина."""


def run(seeds: range, cfg: Config, overwrite: bool = False) -> Path:
    """Собрать дома seeds; вернуть путь к описи. overwrite — снести собранное и начать заново."""
    root = cfg.data.paths.samples_dir
    folder = root / Source.SYNTHETIC
    state = _begin(folder, cfg, overwrite)
    for seed in seeds:
        name = build.sample_id(seed)
        if store.path(root, Source.SYNTHETIC, name).exists():
            continue
        house = build.sample(seed, cfg)
        bad = errors(validate(house.sheet, cfg.checks))
        if bad:
            state["rejected"][name] = [v.message for v in bad]
            _save(folder, state)
        else:
            store.write(house, root)
    return store.write_manifest(root, Source.SYNTHETIC, {"generator": state})


def _begin(folder: Path, cfg: Config, overwrite: bool) -> dict:
    """Состояние сборки: новое или прежнее, если настройки и код те же."""
    fresh = {"config": cfg.synthetic.model_dump(mode="json"), "git_sha": git_sha(),
             "rejected": {}}
    if overwrite and folder.exists():
        for old in folder.glob("*.json"):
            old.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    if not (folder / BUILD).exists():
        if any(folder.glob("*.json")):
            raise BuildError(f"в {folder} лежат примеры неизвестной сборки — нужен --overwrite")
        _save(folder, fresh)
        return fresh
    state = json.loads((folder / BUILD).read_text())
    for key, what in (("config", "настройками"), ("git_sha", "версией кода")):
        if state[key] != fresh[key]:
            raise BuildError(f"в {folder} — сборка с другими {what}: дома вышли бы разными; "
                             "пересобрать — --overwrite")
    return state


def _save(folder: Path, state: dict) -> None:
    (folder / BUILD).write_text(json.dumps(state, ensure_ascii=False, indent=2))
