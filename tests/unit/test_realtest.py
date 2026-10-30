"""Таблица против реального теста одной командой (gf#210; `evaluation: Основная таблица на
реальном тесте`): папки строк в обоих режимах, таблица против всех реальных домов и половины
против половины; без обученной модели строки модели нет."""

import json

from genfacade.metrics import calibrate, realtest
from genfacade.schema import Mode


def test_realtest_builds_rows_and_tables(house, cfg, monkeypatch, tmp_path):
    real = {f"h{i}": house for i in range(4)}
    monkeypatch.setattr(calibrate, "houses", lambda source, split, count, cfg: real)
    realtest.run(cfg, tmp_path, synthetic=0)
    for mode in Mode:
        rows = json.loads((tmp_path / mode / "rows" / "metrics.json").read_text())["rows"]
        assert sorted(k.rsplit("/", 1)[-1] for k in rows) == sorted(
            ["genplan", "generator", *realtest.SUBSTITUTES])
        half = json.loads((tmp_path / mode / "half" / "metrics.json").read_text())["rows"]
        assert [r["count"] for r in half.values()] == [2]
