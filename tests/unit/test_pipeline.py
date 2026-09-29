import json

from genfacade import pipeline
from genfacade.render.parse import parse_sheet_svg


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
