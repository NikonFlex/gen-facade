"""tools/tolerance_probe.py (gf#403): датчик на домах с известным разбросом."""
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from genfacade.schema import Element, ElementClass

PATH = Path(__file__).resolve().parents[2] / "tools" / "tolerance_probe.py"
SPEC = spec_from_file_location("tolerance_probe", PATH)
probe = module_from_spec(SPEC)
sys.modules["tolerance_probe"] = probe  # dataclass ищет свой модуль
SPEC.loader.exec_module(probe)


def window(name: str, x: float, y: float, floor: int, w: float = 1.0, h: float = 1.2) -> Element:
    return Element(id=name, cls=ElementClass.WINDOW, x_m=x, y_m=y, w_m=w, h_m=h, floor=floor)


def wall(house, *windows: Element):
    """Лист дома с одной стеной из этих окон (участков у стены нет)."""
    side = house.facades[0].model_copy(update={"elements": list(windows), "runs": []})
    return house.model_copy(update={"facades": [side]})


def test_row_ranges_are_known(house):
    # верх: 2,0 / 2,1 / 2,3 — размах 0,3; низ: 0,8 / 0,9 / 1,1 — тот же размах
    ws = [window("a", 0.5, 0.8, 1), window("b", 2.5, 0.9, 1), window("c", 5.5, 1.1, 1)]
    got = probe.measure([wall(house, *ws)])
    assert got.values["top_range"] == pytest.approx([0.3])
    assert got.values["bottom_range"] == pytest.approx([0.3])
    assert got.values["gap_range"] == pytest.approx([1.0])  # просветы 1,0 и 2,0


def test_axis_pairs_between_floors(house):
    ws = [window("a", 1.0, 0.8, 1), window("b", 1.1, 3.8, 2, w=0.9),
          window("c", 6.0, 0.8, 1)]  # у c пары нет: над ней окно не перекрывает по x
    got = probe.measure([wall(house, *ws)])
    assert got.values["axis_left"] == pytest.approx([0.1])
    assert got.values["axis_right"] == pytest.approx([0.0])
    assert got.values["axis_center"] == pytest.approx([0.05])


def test_line_jump_from_house_median(house):
    ws = [window("a", 0.5, 0.8, 1), window("b", 3.0, 0.8, 1), window("c", 6.0, 1.1, 1)]
    got = probe.measure([wall(house, *ws)])
    assert sorted(got.values["line_jump"]) == pytest.approx([0.0, 0.0, 0.3])


def test_percentiles_and_shares():
    assert probe.percentiles([0.0, 1.0, 2.0, 3.0, 4.0], [50, 100]) == [2.0, 4.0]
    assert probe.share_within([0.0, 0.05, 0.2], 0.05) == pytest.approx(2 / 3)
    assert probe.near_axis_share([0.0, 0.03, 0.04, 0.9], 0.01, 0.05) == pytest.approx(2 / 3)


def test_probe_catches_broken_row_grouping(house, monkeypatch):
    """Красное на сломанном коде: если ряд не делить по этажам, размах верха станет этажным."""
    ws = [window("a", 0.5, 0.8, 1), window("b", 3.0, 3.8, 2)]
    assert probe.measure([wall(house, *ws)]).values["top_range"] == []
    monkeypatch.setattr(probe, "rows", lambda f: [sorted(probe._windows(f), key=lambda w: w.x_m)])
    assert probe.measure([wall(house, *ws)]).values["top_range"] == pytest.approx([3.0])
