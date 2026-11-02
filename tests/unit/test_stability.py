"""Сводка устойчивости по вариантам сэмплинга (gf#257): числа — из metrics.json вариантов,
разброс — только по вариантам, отличающимся одним seed. Реальный тест не гоняется: папки
вариантов собраны руками."""

import json
import statistics

import pytest

from genfacade.metrics import stability
from genfacade.schema import Mode


def _row(c2st, fid=None, valid=1.0, count=4):
    return {"count": count, "valid": valid, "c2st": c2st, "fid": fid, "house_density": 0.5,
            "house_marginal": -1.0, "windows_per_wall": 2.0}


def _variant(root, name, model, genplan=None):
    """Папка варианта: rows и half в обоих режимах, как у `genfacade realtest`."""
    for mode in Mode:
        for part, rows in (("rows", {f"/x/{mode}/model-m": model,
                                     f"/x/{mode}/genplan": genplan or _row(0.9)}),
                           ("half", {f"/x/{mode}/half-a": _row(0.6)})):
            folder = root / name / mode / part
            folder.mkdir(parents=True)
            (folder / "metrics.json").write_text(json.dumps({"rows": rows}))


@pytest.fixture
def root(tmp_path):
    _variant(tmp_path, "seed=0", _row(0.70, fid=10.0, valid=0.75))
    _variant(tmp_path, "seed=1", _row(0.80, fid=14.0))
    _variant(tmp_path, "seed=10", _row(0.90))
    _variant(tmp_path, "temperature=0.5,seed=0", _row(0.10))
    return tmp_path


def test_every_row_and_variant_listed_per_mode(root, cfg):
    text = stability.run(root, cfg).read_text()
    for mode in Mode:
        assert f"## {mode}" in text
    lines = [line for line in text.splitlines() if line.startswith("| model-m | ")]
    assert len(lines) == (4 + 1) * len(Mode)      # четыре варианта и строка разброса
    assert "| model-m | seed=0 | 3/4 | 0.700 | 10.000 | 0.500 | -1.000 | 2.000 |" in lines
    assert "| model-m | temperature=0.5,seed=0 | 4/4 | 0.100 | — |" in "\n".join(lines)


def test_variants_in_numeric_order(root):
    assert stability._variants(root)[:3] == ["seed=0", "seed=1", "seed=10"]


def test_spread_counts_only_seed_variants(root, cfg):
    """Вариант с temperature в разброс по seed не входит: иначе он бы утащил среднее c2st."""
    text = stability.run(root, cfg).read_text()
    sd = statistics.stdev([0.70, 0.80, 0.90])
    row = next(line for line in text.splitlines()
               if line.startswith("| model-m | 0.917 ± "))     # годных: 3/4, 4/4, 4/4
    assert f"| 0.800 ± {sd:.3f} |" in row
    assert text.count("### Разброс по seed (n = 3: seed=0, seed=1, seed=10)") == len(Mode)


def test_fid_missing_in_some_variants_is_averaged_over_the_rest(root, cfg):
    text = stability.run(root, cfg).read_text()
    assert f"| 12.000 ± {statistics.stdev([10.0, 14.0]):.3f} |" in text   # у seed=10 FID нет
    assert "| genplan | 1.000 ± 0.000 | 0.900 ± 0.000 | — |" in text     # FID нигде нет


def test_one_seed_variant_has_no_spread(tmp_path, cfg):
    _variant(tmp_path, "seed=0", _row(0.7))
    _variant(tmp_path, "top_k=20,seed=0", _row(0.6))
    text = stability.run(tmp_path, cfg).read_text()
    assert "разброса нет" in text


def test_empty_folder_refused(tmp_path, cfg):
    with pytest.raises(FileNotFoundError, match="нет вариантов"):
        stability.run(tmp_path, cfg)
