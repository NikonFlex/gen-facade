"""Конвейер genfacade run на простом доме: трасса шагов 1–6, нарушения, CLI (gf#52, gf#58)."""

import json

import pytest
from simple_house import SIMPLE, WALL_INTO_WINDOW, before_leaf

from genfacade import cli, pipeline
from genfacade.models import stub
from genfacade.render.parse import parse_sheet_svg
from genfacade.schema import HouseSpec, Mode, Plan, Rule

TEXT = "A simple one-storey house with a flat roof."


def _generate(cfg, out, mode=Mode.WITH_OPENINGS, svg=None):
    req = pipeline.PlanRun(plan=str(SIMPLE), text=TEXT, mode=mode)
    return pipeline.generate(req, svg or SIMPLE.read_text(), out, cfg)


def _meta(out):
    return json.loads((out / pipeline.META).read_text())


@pytest.mark.parametrize("mode", list(Mode))
def test_simple_house_traces_all_six_steps(cfg, tmp_path, mode):
    """Вся цепочка на простом доме: шесть файлов шагов, лист без нарушений."""
    out = _generate(cfg, tmp_path / "run", mode)
    meta = _meta(out)
    assert [s["n"] for s in meta["steps"]] == [1, 2, 3, 4, 5, 6]
    assert all((out / s["file"]).stat().st_size > 0 for s in meta["steps"])
    assert meta["request"] == {"plan": str(SIMPLE), "text": TEXT, "mode": mode}
    assert (meta["errors"], meta["warnings"]) == (0, 0)
    assert json.loads((out / pipeline.VIOLATIONS).read_text()) == []
    assert (out / pipeline.INPUT_PLAN).read_text() == SIMPLE.read_text()


def test_house_from_spec_stub(cfg, tmp_path):
    """Шаг 1 — стаб модели: его спека без изменений."""
    out = _generate(cfg, tmp_path / "run")
    spec = HouseSpec.model_validate(json.loads((out / pipeline.SPEC).read_text())["spec"])
    sides = Plan.model_validate_json((out / pipeline.PLAN_JSON).read_text()).sides
    assert spec == stub.spec_model(TEXT) and len(sides) == 4


def test_marks_only_on_sheet(cfg, tmp_path):
    """Шаги 3–5 — стены без оформления; отметки, оси и подписи — только на листе."""
    out = _generate(cfg, tmp_path / "run")
    for step in (pipeline.UNFOLD, pipeline.LAYOUT, pipeline.SNAPPED):
        svg = (out / step).read_text()
        assert "±0,000" not in svg and "Фасад в осях" not in svg, step
    sheet = (out / pipeline.SHEET).read_text()
    assert "±0,000" in sheet and "Фасад в осях" in sheet


def test_text_does_not_change_house(cfg, tmp_path):
    """Текст сохраняется в запросе, но до модели не читается: дом один и тот же."""
    specs = []
    for i, text in enumerate(["A one-storey flat-roofed cabin.", "Five-storey apartment block."]):
        req = pipeline.PlanRun(plan=str(SIMPLE), text=text)
        out = pipeline.generate(req, SIMPLE.read_text(), tmp_path / f"run{i}", cfg)
        assert json.loads((out / pipeline.REQUEST).read_text())["text"] == text
        specs.append((out / pipeline.SPEC).read_text())
    assert specs[0] == specs[1]


def test_unfold_step_has_walls_but_no_elements(cfg, tmp_path):
    unfold_svg = (_generate(cfg, tmp_path / "run") / pipeline.UNFOLD).read_text()
    assert unfold_svg.count('class="wall"') == 4
    assert all(parsed == ([], []) for parsed in parse_sheet_svg(unfold_svg).values())


def test_violations_marked_on_step_5_only(cfg, tmp_path, simple_svg):
    out = _generate(cfg, tmp_path / "run", svg=simple_svg(before_leaf(WALL_INTO_WINDOW)))
    violations = json.loads((out / pipeline.VIOLATIONS).read_text())
    assert {v["rule"] for v in violations} == {Rule.FORBIDDEN}
    assert (_meta(out)["errors"], _meta(out)["warnings"]) == (1, 0)
    snapped = (out / pipeline.SNAPPED).read_text()
    assert snapped.count('class="violation error"') == len(violations)
    assert 'class="violation' not in (out / pipeline.SHEET).read_text()
    assert 'class="forbidden-zone"' in (out / pipeline.LAYOUT).read_text()


def test_run_dirs_do_not_collide(tmp_path):
    first = pipeline.new_run_dir(tmp_path, "дом 1")
    first.mkdir()
    second = pipeline.new_run_dir(tmp_path, "дом 1")
    assert second != first and pipeline.RUN_ID.match(second.name)


def test_cli_runs_simple_house(tmp_path, capsys):
    cli.main(["run", str(SIMPLE), "-t", TEXT, "-o", str(tmp_path / "run")])
    assert capsys.readouterr().out.strip() == str(tmp_path / "run")
    assert (tmp_path / "run" / pipeline.SHEET).exists()


def test_cli_explains_plan_stub_does_not_know(tmp_path, simple_svg):
    """Дом 9 × 5 м — план честный, но стаб знает только простой дом 10 × 5."""
    shorter = tmp_path / "shorter.svg"
    shorter.write_text(simple_svg(
        ('<rect x="800" y="100" width="300"', '<rect x="800" y="100" width="200"'),
        ('<rect x="890" y="585" width="210"', '<rect x="890" y="585" width="110"'),
        ('<rect x="1085" y="100"', '<rect x="985" y="100"'),
        ('<rect x="1085" y="400"', '<rect x="985" y="400"'),
        ('<rect x="1085" y="250"', '<rect x="985" y="250"')))
    with pytest.raises(SystemExit, match="модель не ответила: стаб знает только простой дом"):
        cli.main(["run", str(shorter), "-t", "house", "-o", str(tmp_path / "run")])


def test_cli_rejects_defective_plan(tmp_path):
    bad = tmp_path / "bad.svg"
    bad.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
                   '<rect x="1" y="1" width="5" height="1" fill="#000000"/></svg>')
    with pytest.raises(SystemExit, match="план отклонён: контур не замкнулся"):
        cli.main(["run", str(bad), "-t", "house", "-o", str(tmp_path / "run")])
