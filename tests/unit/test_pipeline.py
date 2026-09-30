import json
from pathlib import Path

import pytest

from genfacade import cli, pipeline
from genfacade.render.parse import parse_sheet_svg
from genfacade.schema import Violation


def test_trace_has_every_step_file(load_house, cfg, tmp_path):
    out = pipeline.run(load_house("house_gable"), tmp_path / "run", cfg, source="тест")
    meta = json.loads((out / pipeline.META).read_text())
    assert [s["n"] for s in meta["steps"]] == [1, 2, 3, 4, 5, 6]
    for step in meta["steps"]:
        if step["file"] is not None:
            assert (out / step["file"]).stat().st_size > 0
    assert (out / meta["input"]).exists() and (out / meta["sheet_json"]).exists()


def test_unfold_step_has_walls_but_no_elements(load_house, cfg, tmp_path):
    out = pipeline.run(load_house("house_gable"), tmp_path / "run", cfg, source="тест")
    unfold_svg = (out / pipeline.UNFOLD).read_text()
    assert unfold_svg.count('class="wall"') == 4
    assert all(parsed == ([], []) for parsed in parse_sheet_svg(unfold_svg).values())


def test_run_dirs_do_not_collide(tmp_path):
    first = pipeline.new_run_dir(tmp_path, "дом 1")
    first.mkdir()
    second = pipeline.new_run_dir(tmp_path, "дом 1")
    assert second != first and pipeline.RUN_ID.match(second.name)


EXAMPLE = Path(__file__).parents[2] / "materials" / "genplan-plan-example.svg"
TEXT = "Two-storey classic house with a gable roof."


def _generate(cfg, out, mode="with_openings", seed=0):
    req = pipeline.PlanRun(plan=str(EXAMPLE), text=TEXT, mode=mode, seed=seed)
    return pipeline.generate(req, EXAMPLE.read_text(), out, cfg)


def test_plan_run_traces_all_six_steps(cfg, tmp_path):
    out = _generate(cfg, tmp_path / "run", mode="blind")
    meta = json.loads((out / pipeline.META).read_text())
    assert meta["kind"] == "plan" and meta["request"]["mode"] == "blind"
    assert all(s["file"] and (out / s["file"]).stat().st_size > 0 for s in meta["steps"])
    spec = json.loads((out / pipeline.SPEC).read_text())
    assert spec["spec"]["floors"] == 2 and spec["from_text"]["floors"] == "Two-storey"
    assert json.loads((out / pipeline.VIOLATIONS).read_text()) == []
    assert (out / pipeline.INPUT_PLAN).read_text() == EXAMPLE.read_text()


def test_violations_marked_on_step_5_only(cfg, tmp_path):
    # режим 2 на примере: окно плана в запретной зоне — дефект GenPlan
    out = _generate(cfg, tmp_path / "run")
    violations = json.loads((out / pipeline.VIOLATIONS).read_text())
    assert {v["rule"] for v in violations} == {"forbidden"}
    snapped = (out / pipeline.SNAPPED).read_text()
    assert snapped.count('class="violation error"') == len(violations)
    assert 'class="violation' not in (out / pipeline.SHEET).read_text()
    assert 'class="forbidden-zone"' in (out / pipeline.LAYOUT).read_text()


def test_retry_stops_when_errors_do_not_change(cfg, tmp_path):
    meta = json.loads((_generate(cfg, tmp_path / "run") / pipeline.META).read_text())
    assert [a["seed"] for a in meta["attempts"]] == [0, 1]  # дефект плана повтором не лечится


def test_retry_takes_next_seed_until_clean(cfg, tmp_path, monkeypatch):
    """Первые две попытки — с подложенной ошибкой, каждый раз новой: третья чистая."""
    real, calls = pipeline.validate, []

    def fake(sheet, checks):
        calls.append(1)
        planted = Violation(rule="overlap", severity="error", side=0, element=f"x{len(calls)}",
                            message="подложено")
        return real(sheet, checks) + ([planted] if len(calls) < 3 else [])

    monkeypatch.setattr(pipeline, "validate", fake)
    out = _generate(cfg, tmp_path / "run", mode="blind", seed=10)
    meta = json.loads((out / pipeline.META).read_text())
    assert [a["errors"] for a in meta["attempts"]] == [1, 1, 0] and meta["seed_used"] == 12


def test_ridge_along_longest_side(cfg, tmp_path):
    spec = json.loads((_generate(cfg, tmp_path / "run") / pipeline.SPEC).read_text())["spec"]
    # пример: 5.47 м вдоль x, 4.23 м вдоль y
    assert spec["roof"]["ridge_axis"] == "x"


def test_cli_rejects_defective_plan(tmp_path):
    bad = tmp_path / "bad.svg"
    bad.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                   '<rect x="1" y="1" width="5" height="1" fill="#000000"/></svg>')
    with pytest.raises(SystemExit, match="план отклонён: контур не замкнулся"):
        cli.main(["run", str(bad), "-t", "house", "-o", str(tmp_path / "run")])
