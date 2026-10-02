"""Корпус для обучения: дома источника → номера токенов одним файлом (gf#73)."""

import json

import numpy
import pytest

from genfacade import cli
from genfacade.datasets import store
from genfacade.datasets.synthetic import batch
from genfacade.schema import Mode, Source, Split
from genfacade.train import corpus, tokens

HOUSES = 6


@pytest.fixture
def built(at):
    """Настройки и собранные синтетические дома; половина — в val, чтобы были обе части."""
    cfg = at("data", "[build]\nval_share = 0.5\n")
    batch.run(range(HOUSES), cfg)
    return cfg


def _folder(cfg):
    return cfg.data.paths.samples_dir / Source.SYNTHETIC


def _sequences(cfg) -> list[tuple[str, str, str, list[str]]]:
    """Корпус с диска, как его прочтёт обучение: дом, часть, режим, токены словами."""
    data = numpy.load(_folder(cfg) / corpus.ARRAYS)
    words, starts = data["vocabulary"], [0, *data["ends"][:-1]]
    return [(str(data["sample"][i]), corpus.SPLITS[data["split"][i]],
             corpus.MODES[data["mode"][i]], [str(w) for w in words[data["ids"][a:b]]])
            for i, (a, b) in enumerate(zip(starts, data["ends"], strict=True))]


def test_every_house_is_written_in_every_mode(built):
    manifest = json.loads(corpus.build(Source.SYNTHETIC, built).read_text())
    root, rows = built.data.paths.samples_dir, _sequences(built)
    expected = []
    for name in store.ids(root, Source.SYNTHETIC):
        sample = store.read(root, Source.SYNTHETIC, name)
        expected += [(name, sample.split, mode, tokens.encode(sample.sheet, mode, built))
                     for mode in Mode]
    assert rows == expected
    assert {r[1] for r in rows} == {Split.TRAIN, Split.VAL}
    lengths = sorted(len(r[3]) for r in rows)
    assert (manifest["houses"], manifest["sequences"]) == (HOUSES, HOUSES * len(Mode))
    assert manifest["tokens"] == sum(lengths)
    assert manifest["length"] == {"min": lengths[0], "median": lengths[len(lengths) // 2],
                                  "max": lengths[-1]}
    assert manifest["by_mode"] == {mode: HOUSES for mode in Mode}
    assert sum(manifest["by_split"].values()) == len(rows)
    assert manifest["vocabulary"] == len(tokens.vocabulary(built))
    assert manifest["skipped"] == {}


def test_house_that_is_not_written_is_skipped_in_both_modes(built):
    """Дом со стилем не из словаря в корпус не идёт, а в описи видно, какой и почему."""
    root, bad = built.data.paths.samples_dir, store.ids(built.data.paths.samples_dir,
                                                         Source.SYNTHETIC)[2]
    sample = store.read(root, Source.SYNTHETIC, bad)
    spec = sample.sheet.spec.model_copy(update={"style": "gothic"})
    store.write(sample.model_copy(update={"sheet": sample.sheet.model_copy(
        update={"spec": spec})}), root)
    manifest = json.loads(corpus.build(Source.SYNTHETIC, built).read_text())
    assert list(manifest["skipped"]) == [bad] and "gothic" in manifest["skipped"][bad]
    assert manifest["houses"] == HOUSES - 1
    assert bad not in {r[0] for r in _sequences(built)}


def test_source_without_houses_is_refused(at):
    cfg = at("empty")
    _folder(cfg).mkdir(parents=True)
    with pytest.raises(corpus.CorpusError, match="нет домов"):
        corpus.build(Source.SYNTHETIC, cfg)


def test_tokens_command_writes_the_corpus(tmp_path, capsys):
    (tmp_path / "data.toml").write_text(f'[paths]\nsamples_dir = "{tmp_path / "samples"}"\n')
    cli.main(["-c", str(tmp_path), "synth", "-n", "3"])
    capsys.readouterr()
    cli.main(["-c", str(tmp_path), "tokens"])
    manifest = json.loads(open(capsys.readouterr().out.strip()).read())
    assert manifest["houses"] == 3 and manifest["source"] == Source.SYNTHETIC
    (tmp_path / "data.toml").write_text(f'[paths]\nsamples_dir = "{tmp_path / "none"}"\n')
    with pytest.raises(SystemExit, match="корпус не собран"):
        cli.main(["-c", str(tmp_path), "tokens"])
