"""Свод правил фасада (gf#209; `evaluation: Без норм ГОСТ` — нормы в своде, не в валидаторе).

Каждый вид проверки — с двух концов: дом, где правило выполнено, проходит, а дом, где оно
нарушено, — нет. Реестр в config/guidelines.toml проверяется на форму: параметры каждого правила —
те, что знает его проверка, у непроверяемого правила — причина.
"""

import pytest

from genfacade import guidelines
from genfacade.config import Guideline
from genfacade.schema import (
    BuildingType,
    Element,
    ElementClass,
    FacadeSheet,
    GuidelineCheck,
    HouseSpec,
    Material,
    Plan,
    Roof,
    RoofKind,
    Sample,
    Side,
    SideFacade,
    Source,
    Split,
)

W, D, S, B, C = (ElementClass.WINDOW, ElementClass.DOOR, ElementClass.SILL, ElementClass.BLIND,
                 ElementClass.CANOPY)
PLINTH, FLOOR = 0.5, 3.0  # два этажа по 3 м над цоколем 0,5 м: пол второго — 3,5, карниз — 6,5
LENGTH = 10.0


def _el(cls, x, y, w, h, i="", parent=None) -> Element:
    return Element(id=i or f"{cls}{x}{y}", cls=cls, x_m=x, y_m=y, w_m=w, h_m=h, parent=parent)


def _sheet(elements, heights=(FLOOR, FLOOR)) -> FacadeSheet:
    spec = HouseSpec(building_type=BuildingType.COTTAGE, floors=len(heights),
                     floor_heights_m=list(heights), plinth_m=PLINTH,
                     eaves_m=PLINTH + sum(heights), roof=Roof(kind=RoofKind.FLAT),
                     materials=[Material(id="main", kind="plaster")])
    side = Side(index=0, length_m=LENGTH, orientation=(0.0, -1.0), has_entrance=True)
    return FacadeSheet(spec=spec, facades=[SideFacade(side=side, elements=elements)])


def _plan() -> Plan:
    return Plan(walls=[], outline=[(0, 0), (0, 8), (LENGTH, 8), (LENGTH, 0)], scale_m_per_px=1.0,
                source=Source.MANUAL)


def _win(x=2.0, sill=0.85, w=1.0, h=1.5, floor=1, i="") -> Element:
    return _el(W, x, PLINTH + (floor - 1) * FLOOR + sill, w, h, i)


def _door(x=4.5, w=0.9, h=2.1) -> Element:
    return _el(D, x, PLINTH, w, h, "door")


TOP = PLINTH + 0.85 + 1.5  # верх обычного окна первого этажа

# вид проверки, параметры, элементы дома, где правило выполнено, и где нарушено
CASES = [
    (GuidelineCheck.ASPECT, {"cls": W, "min": 1.0}, [_win()], [_win(w=2.0, h=1.0)]),
    (GuidelineCheck.SIZE_ROW, {"cls": W, "widths": [0.9, 1.2], "heights": [1.5], "tol_m": 0.03},
     [_win(w=0.9)], [_win(w=1.0)]),
    (GuidelineCheck.MODULE, {"cls": W, "module_m": 0.1, "tol_m": 0.01},
     [_win(w=0.9)], [_win(w=0.95)]),
    (GuidelineCheck.SILL_HEIGHT, {"skip_below_m": 0.3, "min": 0.8, "max": 0.9},
     [_win(), _win(x=6, sill=0.0)], [_win(sill=1.2)]),
    (GuidelineCheck.HEAD_HEIGHT, {"min": 2.0, "max": 2.5}, [_win()], [_win(h=2.0)]),
    (GuidelineCheck.HEAD_LINE, {"tol_m": 0.05}, [_win(), _win(x=6)], [_win(), _win(x=6, h=1.3)]),
    (GuidelineCheck.VERTICAL_AXES, {"tol_m": 0.1}, [_win(), _win(floor=2)],
     [_win(), _win(x=5, floor=2)]),
    (GuidelineCheck.CORNER_DISTANCE, {"cls": W, "min": 0.8}, [_win(x=1.0)], [_win(x=0.3)]),
    (GuidelineCheck.PIER_MIN, {"min": 0.6}, [_win(), _win(x=4)], [_win(), _win(x=3.2)]),
    (GuidelineCheck.OPENING_SHARE, {"max": 0.5}, [_win()], [_el(W, 0.5, 1.0, 9.0, 4.0)]),
    (GuidelineCheck.FLOOR_OPENING_WIDTH, {"min": 0.1}, [_win(), _win(floor=2)], [_win()]),
    (GuidelineCheck.WINDOW_TYPES, {"per_facade": 1, "per_house": 1, "tol_m": 0.05},
     [_win(), _win(x=6)], [_win(), _win(x=6, w=1.4)]),
    (GuidelineCheck.DOOR_SIZE, {"min_w": 0.8, "min_h": 1.9}, [_door()], [_door(w=0.7, h=1.8)]),
    (GuidelineCheck.DOOR_HEAD_LINE, {"tol_m": 0.05}, [_win(), _door(h=TOP - PLINTH)],
     [_win(), _door()]),
    (GuidelineCheck.SILL_UNDER_WINDOW, {"skip_below_m": 0.3, "tol_m": 0.05},
     [_win(i="w"), _el(S, 1.95, PLINTH + 0.79, 1.1, 0.06, parent="w")], [_win()]),
    (GuidelineCheck.CANOPY_OVER_ENTRANCE, {}, [_door(), _el(C, 4.2, 2.7, 1.5, 0.2)], [_door()]),
    (GuidelineCheck.SHUTTER_WIDTH, {"min": 0.4, "max": 0.6},
     [_win(i="w"), _el(B, 1.5, 1.35, 0.5, 1.5, parent="w")],
     [_win(i="w"), _el(B, 1.0, 1.35, 1.0, 1.5, parent="w")]),
    (GuidelineCheck.HEAD_TO_EAVES, {"min": 0.3}, [_win(floor=2)], [_win(floor=2, h=2.0)]),
    (GuidelineCheck.LOWER_NOT_SMALLER, {}, [_win(), _win(floor=2, h=1.2)],
     [_win(h=1.0), _win(floor=2)]),
    (GuidelineCheck.SYMMETRY, {"tol_m": 0.05}, [_door(x=4.55), _win(x=2), _win(x=7)],
     [_door(x=4.55), _win(x=2), _win(x=6)]),
]


@pytest.mark.parametrize(("check", "params", "good", "bad"), CASES, ids=[c[0] for c in CASES])
def test_check_passes_good_and_fails_bad(check, params, good, bad):
    run = guidelines.CHECKS[check]
    passed, failed = run(params, _sheet(good), None), run(params, _sheet(bad), None)
    assert passed and all(passed)
    assert failed and not all(failed)


@pytest.mark.parametrize(("check", "params", "good", "bad"), [
    (GuidelineCheck.PLINTH_HEIGHT, {"min": 0.3, "max": 0.9}, {}, {"min": 0.6}),
    (GuidelineCheck.FLOOR_HEIGHT, {"min": 2.5}, {}, {"min": 3.2}),
    (GuidelineCheck.LIGHT_RATIO, {"min": 0.125}, {}, {"min": 0.5}),
], ids=["plinth_height", "floor_height", "light_ratio"])
def test_house_wide_check_turns_red_with_stricter_bound(check, params, good, bad):
    """Цоколь, этажи, свет — параметры дома: тот же дом при более строгой границе не проходит."""
    sheet = _sheet([_el(W, 0.5, 1.0, 9.0, 2.5)])
    run = guidelines.CHECKS[check]
    assert all(run({**params, **good}, sheet, _plan()))
    assert not all(run(bad, sheet, _plan()))


def test_light_ratio_needs_plan():
    assert guidelines.light_ratio({"min": 0.125}, _sheet([_win()]), None) == []


def test_every_check_has_function_and_params():
    assert set(guidelines.CHECKS) == set(GuidelineCheck) == set(guidelines.PARAMS)


def test_registry_params_match_checks(cfg):
    for g in cfg.guidelines.guideline:
        required, optional = guidelines.PARAMS[g.check]
        assert required <= set(g.params) <= required | optional, g.id


def test_registry_is_well_formed(cfg):
    ids = [g.id for g in cfg.guidelines.guideline]
    assert len(ids) == len(set(ids))
    for g in cfg.guidelines.guideline:
        assert g.source, g.id
        assert g.check is not GuidelineCheck.NONE or g.note, f"{g.id}: нет причины"


def test_house_without_cases_is_not_counted():
    g = Guideline(id="x", text="", check=GuidelineCheck.DOOR_SIZE,
                  params={"min_w": 0.8, "min_h": 1.9}, applies=[], source=[])
    def sample(es):
        return Sample(id="h", source=Source.MANUAL, split=Split.TEST, sheet=_sheet(es))
    m = guidelines.measure(g, [sample([_door()]), sample([_win()]), sample([_door(w=0.7)])])
    assert (m.houses, m.passed, m.cases) == (2, 1, 2)


def test_table_lists_every_guideline(cfg):
    rows = [(g, guidelines.Measured(houses=0, passed=0, cases=0, share=None))
            for g in cfg.guidelines.guideline]
    text = guidelines.table(rows, 0)
    assert all(f"**{g.id}**" in text for g in cfg.guidelines.guideline)
