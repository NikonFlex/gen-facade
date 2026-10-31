"""Сборка синтетики пачкой: дома по seed подряд → примеры и опись
(`data: Сборка синтетики по seed`).

Сборку можно оборвать и запустить снова: готовые дома пропускаются. Чем собрано — в файле
`_build.json` рядом с примерами: настройки, версия кода генератора и отброшенные дома. Дом с
ошибкой валидатора в датасет не пишется.
"""

import hashlib
import json
from pathlib import Path

from genfacade.config import Config
from genfacade.datasets import store
from genfacade.datasets.synthetic import build
from genfacade.schema import Source
from genfacade.validate import errors, validate

BUILD = "_build.json"
PACKAGE = Path(__file__).parents[2]
# Код, от которого зависят дома сборки (`data: Сборка не смешивает настройки`): генератор,
# запись его плана в SVG GenPlan и препроцессор, который этот план читает (build.sample),
# развёртка, схема примера, валидатор (отбраковка), вывод декора (derive.py) и формат файлов
# примера. Коммит всего репо не годится: правка смотрелки, обучения или документов домов не меняет,
# а пересборку требовала бы. pipeline.py не входит: из него сборке нужна только walls() — обёртка
# над unfold.
GENERATOR_CODE = ("datasets/synthetic", "datasets/genplan_writer.py", "datasets/store.py",
                  "plan", "unfold.py", "schema.py", "validate.py", "derive.py")


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
    fresh = {"config": _settings(cfg), "code": code_version(), "rejected": {}}
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
    for key, what in (("config", "другими настройками"), ("code", "другой версией кода")):
        # .get: у сборки, записанной до версии кода генератора, ключа "code" нет
        if state.get(key) != fresh[key]:
            raise BuildError(f"в {folder} — сборка с {what}: дома вышли бы разными; "
                             "пересобрать — --overwrite")
    return state


def _settings(cfg: Config) -> dict:
    """Настройки, от которых зависят дома: генератор, препроцессор его плана, валидатор."""
    return {"synthetic": build.with_norms(cfg).synthetic.model_dump(mode="json"),
            "derive": cfg.derive.model_dump(mode="json"),
            "plan": cfg.plan.model_dump(mode="json"), "checks": cfg.checks.model_dump(mode="json")}


def code_version() -> str:
    """Хеш исходников GENERATOR_CODE: имя файла и содержимое, в постоянном порядке."""
    digest = hashlib.sha256()
    for path in sorted(_sources()):
        digest.update(path.relative_to(PACKAGE).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _sources() -> list[Path]:
    found = []
    for name in GENERATOR_CODE:
        path = PACKAGE / name
        found += sorted(path.rglob("*.py")) if path.is_dir() else [path]
    return found


def _save(folder: Path, state: dict) -> None:
    (folder / BUILD).write_text(json.dumps(state, ensure_ascii=False, indent=2))
