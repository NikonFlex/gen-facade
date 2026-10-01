"""Сборка синтетики пачкой: продолжение после обрыва, настройки сборки, отбраковка, части."""

import json

import pytest

from genfacade import config
from genfacade.datasets import store
from genfacade.datasets.synthetic import batch, build
from genfacade.schema import Rule, Severity, Source, Split, Violation


@pytest.fixture
def at(tmp_path):
    """Настройки с корнем данных в tmp_path/<имя>; extra — свои строки synthetic.toml."""
    def load(name: str, extra: str = "") -> config.Config:
        folder = tmp_path / f"cfg-{name}-{len(extra)}"
        folder.mkdir()
        (folder / "data.toml").write_text(f'[paths]\nsamples_dir = "{tmp_path / name}"\n')
        (folder / "synthetic.toml").write_text(extra)
        return config.load(folder)

    return load


def _files(cfg) -> dict[str, str]:
    """Собранные дома: имя → содержимое файла."""
    root = cfg.data.paths.samples_dir
    return {i: store.path(root, Source.SYNTHETIC, i).read_text()
            for i in store.ids(root, Source.SYNTHETIC)}


def _manifest(path) -> dict:
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if k != "date"}


def test_resumed_build_equals_uninterrupted(at):
    whole, broken = at("whole"), at("broken")
    straight = batch.run(range(8), whole)
    batch.run(range(3), broken)  # «оборвалась» после трёх домов
    resumed = batch.run(range(8), broken)
    assert _files(broken) == _files(whole) and len(_files(whole)) == 8
    assert _manifest(resumed) == _manifest(straight)
    assert not list(resumed.parent.glob("*.part"))


def test_ready_houses_are_not_rebuilt(at):
    cfg = at("data")
    batch.run(range(3), cfg)
    ready = store.path(cfg.data.paths.samples_dir, Source.SYNTHETIC, build.sample_id(1))
    ready.write_text(ready.read_text() + "\n")  # пометка: файл тот же, что был
    batch.run(range(5), cfg)
    assert ready.read_text().endswith("\n\n") or ready.read_text().endswith("}\n")
    assert len(_files(cfg)) == 5


def test_other_settings_stop_the_build_until_overwrite(at):
    batch.run(range(3), at("data"))
    changed = at("data", "[house]\nwall_m = 0.2\n")
    with pytest.raises(batch.BuildError, match="другими настройками"):
        batch.run(range(5), changed)
    assert len(_files(changed)) == 3  # отказ ничего не тронул
    batch.run(range(5), changed, overwrite=True)
    walls = [store.read(changed.data.paths.samples_dir, Source.SYNTHETIC, i).plan.walls[0]
             for i in _files(changed)]
    assert len(walls) == 5 and all(w.y1_m - w.y0_m == pytest.approx(0.2) for w in walls)


def test_samples_of_unknown_build_stop_the_build(at, sample):
    cfg = at("data")
    store.write(sample, cfg.data.paths.samples_dir)  # пример, положенный не сборкой
    with pytest.raises(batch.BuildError, match="неизвестной сборки"):
        batch.run(range(2), cfg)


def test_house_with_validator_error_is_left_out(at, monkeypatch):
    """Брак в датасет не пишется, а в описи и в файле сборки видно, что и почему отброшено."""
    cfg, bad = at("data"), build.sample_id(2)
    real = build.sample

    def spoil(seed, cfg):
        house = real(seed, cfg)
        if house.id == bad:  # карниз вылез за стену
            house.sheet.facades[0].elements[-1].x_m = -1.0
        return house

    monkeypatch.setattr(build, "sample", spoil)
    saved = _manifest(batch.run(range(4), cfg))
    assert bad not in _files(cfg) and saved["samples"] == 3
    assert list(saved["generator"]["rejected"]) == [bad]
    assert "выходит за силуэт" in saved["generator"]["rejected"][bad][0]
    state = json.loads((cfg.data.paths.samples_dir / Source.SYNTHETIC / batch.BUILD).read_text())
    assert list(state["rejected"]) == [bad]


def test_warning_does_not_reject(at, monkeypatch):
    warning = Violation(rule=Rule.FLOOR_ALIGN, severity=Severity.WARNING, message="мелочь")
    monkeypatch.setattr(batch, "validate", lambda sheet, checks: [warning])
    assert _manifest(batch.run(range(2), at("data")))["samples"] == 2


def test_split_depends_only_on_seed(cfg, at):
    rules = cfg.synthetic
    parts = [build.split(s, rules) for s in range(2000)]
    assert parts == [build.split(s, rules) for s in range(2000)]
    assert set(parts) == {Split.TRAIN, Split.VAL}  # в тест синтетика не идёт
    share = parts.count(Split.VAL) / len(parts)
    assert rules.build.val_share / 2 < share < rules.build.val_share * 2
    all_val = at("data", "[build]\nval_share = 1.0\n")
    assert _manifest(batch.run(range(3), all_val))["splits"] == {Split.VAL: 3}


def test_saved_manifest_used_only_while_it_matches_files(at, sample):
    """Смотрелка берёт сохранённую опись; добавили пример мимо сборки — считает заново."""
    cfg = at("data")
    batch.run(range(3), cfg)
    root = cfg.data.paths.samples_dir
    assert "generator" in store.load_manifest(root, Source.SYNTHETIC)
    store.write(sample, root)
    fresh = store.load_manifest(root, Source.SYNTHETIC)
    assert fresh["samples"] == 4 and "generator" not in fresh
