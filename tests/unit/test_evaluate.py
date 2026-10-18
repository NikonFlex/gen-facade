"""Оценка модели шага 4 на val (gf#108): эталон генератора проходит все проверки, глухой режим
не требует окон плана, неразобранный ответ теряет свои проёмы.
"""

import json

import pytest
import tiny_model

from genfacade.datasets.synthetic import batch
from genfacade.metrics import table
from genfacade.schema import Device, Mode, OpeningKind, Rule, Source, Split
from genfacade.train import corpus, evaluate, fit

# долгий: torch — вне быстрой проверки перед коммитом (gf#165)
pytestmark = pytest.mark.slow

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


def test_eval_dumps_sheets_for_metrics(setup, tmp_path):
    """Листы ответов — по папке на кого и режим (gf#16): эталон проходит метрики, ответы
    необученной модели не разбираются — нижний край доли валидных."""
    out = evaluate.run(Source.SYNTHETIC, setup, tmp_path / "eval").parent / evaluate.SHEETS
    ref = out / evaluate.REFERENCE / Mode.BLIND
    rows = {who: table.row(table.load(out / who / Mode.BLIND, setup),
                           table.reference(table.load(ref, setup), setup), setup)
            for who in (evaluate.REFERENCE, evaluate.UNTRAINED)}
    assert (rows["reference"]["valid"], rows["reference"]["plan"]) == (1.0, 1.0)
    assert rows["untrained"]["valid"] == 0.0


def test_independent_sides_take_their_own_house_parameters(setup, monkeypatch):
    """Ablation «независимые стороны» (gf#163): стена k — с параметрами другого дома val того
    же режима; где высоты стен разошлись, валидатор видит несходящиеся углы. Ответы модели
    подменены ответом генератора: расхождение — только от чужих параметров."""
    data, group = _val(setup)
    ev = evaluate.Evaluation(data, group, setup)
    answers = [c.reference for c in group for _ in c.bare.facades]
    monkeypatch.setattr(evaluate, "_answers", lambda sampler, prompts, cfg: (answers, 0.0))
    judged = evaluate.independent(ev, None, setup)
    for case, j in zip(group, judged, strict=True):
        same = [c for c in group if c.mode is case.mode]
        at = same.index(case)
        tops = [max(y for _, y in f.silhouette) for f in j.sheet.facades]
        donors = [same[(at + k + 1) % len(same)].bare.spec.eaves_m for k in range(len(tops))]
        assert tops == pytest.approx(donors)
        assert (Rule.CORNER in {v.rule for v in j.raw}) == (max(tops) - min(tops) > 1e-6)
    monkeypatch.undo()  # дальше — настоящая оценка: строки ablation выгружены листами
    report = evaluate.run(Source.SYNTHETIC, setup, setup.train.paths.runs_dir / "e")
    out = report.parent / evaluate.SHEETS
    for who in (evaluate.CONSTRAINED_RAW, evaluate.INDEPENDENT):
        assert sorted(p.name for p in (out / who).iterdir()) == sorted(Mode)
