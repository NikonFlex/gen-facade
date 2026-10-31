"""Таблица против реального теста одной командой (gf#210; `evaluation: Основная таблица на
реальном тесте`): папки строк в обоих режимах, таблица против всех реальных домов и половины
против половины; без обученной модели строки модели нет. Строки моделей при переобучении
(gf#212, tools/retrain.sh): чекпойнт или листы прошлого прогона, чужой словарь — отказ сразу."""

import json
from types import SimpleNamespace

import pytest

from genfacade import pipeline
from genfacade.metrics import calibrate, realtest
from genfacade.models.stub import ModelError
from genfacade.schema import Mode

NO_ROWS = realtest.Rows({}, {})


@pytest.fixture
def real(house, monkeypatch):
    """Четыре реальных дома — копии простого."""
    houses = {f"h{i}": house for i in range(4)}
    monkeypatch.setattr(calibrate, "houses", lambda source, split, count, cfg: houses)
    return houses


def _rows(out, mode) -> dict:
    return json.loads((out / mode / "rows" / "metrics.json").read_text())["rows"]


def test_realtest_builds_rows_and_tables(real, cfg, tmp_path):
    realtest.run(cfg, tmp_path, 0, NO_ROWS)
    for mode in Mode:
        assert sorted(k.rsplit("/", 1)[-1] for k in _rows(tmp_path, mode)) == sorted(
            ["genplan", "generator", *realtest.SUBSTITUTES])
        half = json.loads((tmp_path / mode / "half" / "metrics.json").read_text())["rows"]
        assert [r["count"] for r in half.values()] == [2]


def test_summary_has_every_row_of_both_modes(real, cfg, tmp_path):
    realtest.run(cfg, tmp_path, 0, NO_ROWS)
    lines = (tmp_path / realtest.SUMMARY).read_text().splitlines()
    assert lines[0].split(" | ")[3:] == [*cfg.metrics.realtest.summary[:-1],
                                         cfg.metrics.realtest.summary[-1] + " |"]
    body = [line.split(" | ")[:3] for line in lines[2:]]
    names = ["genplan", "generator", *realtest.SUBSTITUTES, "real-half"]
    assert body == [[f"| {n}", m, "2/2" if n == "real-half" else "4/4"]
                    for m in Mode for n in names]


def test_sheets_of_earlier_run_become_a_model_row(real, cfg, tmp_path):
    """Модель другой записи токенов ответила своим кодом: её листы — строкой этой таблицы."""
    earlier = tmp_path / "earlier"
    for mode in Mode:
        calibrate.write(earlier / mode / realtest.MODEL, list(real), list(real.values()))
    out = tmp_path / "now"
    realtest.run(cfg, out, 0, realtest.Rows({}, {"old": earlier}))
    for mode in Mode:
        row = _rows(out, mode)[str(out / mode / "model-old")]
        assert (row["count"], row["valid"]) == (4, 1.0)


def test_model_with_other_vocabulary_refused_before_any_work(real, cfg, tmp_path, monkeypatch):
    stale = SimpleNamespace(words=["<answer>", "lost"])
    monkeypatch.setattr(pipeline, "trained_model", lambda settings: stale)
    with pytest.raises(ModelError, match="словарь"):
        realtest.run(cfg, tmp_path / "out", 0, realtest.Rows({"new": tmp_path / "m.pt"}, {}))
    assert not (tmp_path / "out").exists()


def test_missing_sheets_refused_before_any_work(real, cfg, tmp_path):
    with pytest.raises(FileNotFoundError, match="нет листов модели"):
        realtest.run(cfg, tmp_path / "out", 0, realtest.Rows({}, {"old": tmp_path / "none"}))
    assert not (tmp_path / "out").exists()
