"""tools/markup_compare.py (gf#470): сверка разметки дома с эталоном по видам полей."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "tools" / "markup_compare.py"
SPEC = spec_from_file_location("markup_compare", PATH)
mc = module_from_spec(SPEC)
SPEC.loader.exec_module(mc)

HOUSE = """
id = "st-1"
pdf = "1/sheet.pdf"
roof = "двускатная"
roof_kind = "gable"
pitch_deg = {pitch}
overhang_m = 0.5
unit = "m"
pt_per_unit = 100.0
material = "brick"
plinth = 0.4
floor_heights = [2.8]

[[sides]]
view = "Фасад 1"
page = 1
wall = [100.0, 1100.0]
floor = 500.0
elements = [
  {{ cls = "window", box = [{x0}, 200.0, {x1}, 350.0] }},
  {{ cls = "door", box = [700.0, 260.0, 800.0, 500.0] }},
]
"""


def _write(folder: Path, pitch: float = 30.0, shift: float = 0.0) -> Path:
    folder.mkdir()
    text = HOUSE.format(pitch=pitch, x0=300.0 + shift, x1=400.0 + shift)
    (folder / "st-1.toml").write_text(text)
    return folder


def _run(tmp_path, cfg, pitch=30.0, shift=0.0):
    ref = _write(tmp_path / "ref")
    got = _write(tmp_path / "got", pitch, shift)
    return mc.compare_dirs(ref, got, cfg.data.manual.compare)


def _status(house, row):
    return next(d.status for d in house.diffs if d.row == row)


def test_same_markup_matches_everything(tmp_path, cfg):
    (house,) = _run(tmp_path, cfg)
    assert all(d.status is mc.Status.SAME for d in house.diffs)
    assert all(a == b for a, b in mc.totals([house]).values())
    o = house.openings
    assert (o.ref, o.found, o.extra) == (2, 2, 0)


def test_shifted_window_and_pitch_change(tmp_path, cfg):
    (house,) = _run(tmp_path, cfg, pitch=40.0, shift=100.0)  # 100 pt = 1 м
    assert _status(house, "pitch_deg") is mc.Status.DIFF
    assert _status(house, "roof_kind") is mc.Status.SAME
    o = house.openings
    assert (o.ref, o.found, o.extra) == (2, 1, 1)  # окно не найдено и появилось лишнее; дверь цела


def test_report_lists_missing_house_and_diff(tmp_path, cfg):
    ref = _write(tmp_path / "ref")
    (ref / "st-2.toml").write_text((ref / "st-1.toml").read_text())
    got = _write(tmp_path / "got", pitch=40.0)
    houses = mc.compare_dirs(ref, got, cfg.data.manual.compare)
    text = mc.render(houses, ref, got)
    assert "st-2**: не размечен" in text
    assert "pitch_deg 30 → 40" in text
