"""Датчик `tools/overhang_probe.py` (gf#451): доли свесов по источникам и медианы по виду крыши."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

HOUSE = 'roof_kind = "{kind}"\noverhang_m = {eave}\n{extra}'


def probe():
    path = Path(__file__).resolve().parents[2] / "tools" / "overhang_probe.py"
    spec = spec_from_file_location("overhang_probe", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_counts_sources_and_takes_medians_over_drawn_houses(tmp_path):
    def put(folder: str, name: str, kind: str, eave: float, extra: str = "") -> None:
        (tmp_path / folder).mkdir(exist_ok=True)
        (tmp_path / folder / f"{name}.toml").write_text(
            HOUSE.format(kind=kind, eave=eave, extra=extra), encoding="utf-8")

    drawn = 'overhang_by = "drawing"\n'
    put("a", "h1", "gable", 0.6, drawn + "gable_overhang_m = 0.1\n")
    put("a", "h2", "gable", 0.2, drawn)  # фронтонный не задан — равен карнизному
    put("a", "h3", "gable", 0.4, drawn + "gable_overhang_m = 0.0\n")
    put("a", "h4", "hip", 0.9)  # по умолчанию — в медианы не идёт
    put("b", "h5", "hip", 0.5, drawn)
    text = probe().report(tmp_path)
    assert "a: 3 / 1" in text and "b: 1 / 0" in text and "Всего: 4 / 1" in text
    assert "gable: 3, 0.4, 0.1" in text  # карнизные 0.6, 0.2, 0.4; фронтонные 0.1, 0.2, 0.0
    assert "hip: 1, 0.5, 0.5" in text
