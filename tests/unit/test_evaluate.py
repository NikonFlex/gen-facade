"""Оценка модели шага 4 на val (gf#108): эталон генератора проходит все проверки, глухой режим
не требует окон плана, неразобранный ответ теряет свои проёмы.
"""

import json

import pytest
import tiny_model

from genfacade.datasets.synthetic import batch
from genfacade.schema import Device, Mode, OpeningKind, Source, Split
from genfacade.train import corpus, evaluate, fit

HOUSES = 4
VAL_HALF = "[build]\nval_share = 0.5\n"
EVAL = "[eval]\ncount = 0\nbatch = 8\nuntrained = 2\n"


@pytest.fixture
def setup(at, tmp_path):
    """Дома (половина в val), корпус и крошечная необученная модель с нынешним словарём."""
    cfg = at("data", VAL_HALF, EVAL)
    batch.run(range(HOUSES), cfg)
    corpus.build(Source.SYNTHETIC, cfg)
    path = tiny_model.save(tmp_path / "model.pt", cfg)
    layout = cfg.models.layout.model_copy(update={"checkpoint": path, "device": Device.CPU})
    return cfg.model_copy(update={"models": cfg.models.model_copy(update={"layout": layout})})


def _val(cfg):
    data = fit.load(Source.SYNTHETIC, cfg)
    part = data.parts[Split.VAL]
    return data, evaluate.cases(part, list(range(len(part.ids))), Source.SYNTHETIC, cfg)


def test_blind_mode_does_not_expect_plan_windows(setup):
    _, group = _val(setup)
    for case in group:
        kinds = {o.kind for f in case.bare.facades for o in f.side.openings}
        if case.mode is Mode.BLIND:
            assert OpeningKind.WINDOW not in kinds
        else:
            assert OpeningKind.WINDOW in kinds


def test_reference_answers_pass_every_check(setup):
    data, group = _val(setup)
    ev = evaluate.Evaluation(data, group, setup)
    report, judged = ev.report([c.reference for c in group])
    for mode in Mode:
        s = report["by_mode"][mode]
        assert (s["parsed"], s["valid_raw"], s["plan_openings_in_place"]) == (1.0, 1.0, 1.0)
    assert all(j.error is None for j in judged)
    # ответы train сами себе — дословные повторы
    train = data.parts[Split.TRAIN]
    own = [train.ids[i][train.answer_at[i]:].tolist() for i in range(len(train.ids))]
    assert evaluate.copies(own, ev.train) == 1.0


def test_unparsed_answer_loses_its_plan_openings(setup):
    data, group = _val(setup)
    ev = evaluate.Evaluation(data, group, setup)
    broken = [c.reference[:-1] for c in group]  # без `<end>` — не разбирается
    report, _ = ev.report(broken)
    assert report["all"]["parsed"] == 0.0
    assert report["all"]["plan_openings_in_place"] == 0.0


def test_eval_writes_report_for_model_reference_and_untrained(setup, tmp_path):
    path = evaluate.run(Source.SYNTHETIC, setup, tmp_path / "eval")
    report = json.loads(path.read_text())
    assert report["reference"]["all"]["valid_raw"] == 1.0
    assert report["untrained"]["all"]["count"] == setup.train.eval.untrained
    assert report["model"]["all"]["count"] == report["reference"]["all"]["count"]
    assert set(report["compare"]) == set(Mode)
