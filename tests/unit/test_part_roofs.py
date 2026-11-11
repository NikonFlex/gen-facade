"""Крыша пристройки при генерации (gf#431, `facade: Крыша пристройки при генерации`): крыло ниже
главного на его общей стене — односкатная низом от главного, остальные — крыша дома."""

import math
import sys
from functools import partial
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from test_parts import CFG, TWO_PARTS, l_plan

from genfacade import part_roofs, pipeline, roof
from genfacade.models import stub
from genfacade.schema import Facing, Rect, RoofKind

GABLE = f"{TWO_PARTS} Gable roof."
RULE = CFG.plan.parts


def walls(text: str, rule=RULE):
    return pipeline.walls(stub.spec_model(text, CFG.models.spec), l_plan(), rule)


def test_lower_wing_on_main_gets_shed_roof_away_from_main():
    """Сценарий «Пристройка Г-дома»: крыло 2,05 × 3 м с карнизом 3,25 м у торца главного 7,95 × 5 м
    с карнизом 6,0 м — односкатная 14°, низ на свободной восточной стене; главное — двускатная."""
    sheet = walls(GABLE)
    main, annex = sheet.roofs
    assert main is sheet.spec.roof and main.kind is RoofKind.GABLE
    assert annex.kind is RoofKind.SHED and annex.down_to is Facing.X_PLUS
    assert annex.pitch_deg == RULE.annex_pitch_deg


def test_shed_of_annex_rises_to_wall_of_main():
    """Высокая сторона ската пристройки — у стены главного: 3,25 + 2,05 · tg 14° ≈ 3,76 м; зона под
    кровлей на стене главного — по этому скату, а не по щипцу крыши дома (≈ 4,3 м); свеса за линией
    общей стены нет (gf#431)."""
    sheet = walls(GABLE)
    tan = math.tan(math.radians(RULE.annex_pitch_deg))
    annex = min(roof.roofs(sheet).parts, key=lambda p: p.eaves)
    assert len(annex.slopes) == 1 and annex.eaves == pytest.approx(3.25)
    assert 3.25 + 2.05 * tan == pytest.approx(3.76, abs=0.01)
    under = [z for f in sheet.facades for z in f.side.forbidden if z.y1_m is not None]
    assert max(z.y1_m for z in under) == pytest.approx(3.25 + 2.05 * tan)


def test_same_height_wings_keep_house_roof():
    """Сценарий «Г-дом одной высоты»: у обоих крыльев — крыша дома, своих крыш у частей нет."""
    sheet = walls("A house. Gable roof.", RULE.model_copy(update={"wing_min_m": 3.5}))
    assert len(sheet.wings) == 2 and not sheet.roofs


@pytest.mark.parametrize("text", [f"{TWO_PARTS} Flat roof.", GABLE])
def test_no_annex_roof_on_flat_house_or_when_rule_is_off(text):
    off = RULE.model_copy(update={"annex_shed": False})
    rule = RULE if "Flat" in text else off
    assert not walls(text, rule).roofs


def test_without_rule_house_roof_on_all_parts():
    """Синтетика и разметка вызывают развёртку без правила — крыши частей ставят сами."""
    spec = stub.spec_model(f"{GABLE}", CFG.models.spec).model_copy(update={"wing_floors": 1})
    assert not pipeline.walls(spec, l_plan()).roofs


@pytest.mark.parametrize(("wing", "side"), [
    (Rect(x0_m=10, y0_m=0, x1_m=13, y1_m=3), Facing.X_PLUS),
    (Rect(x0_m=-3, y0_m=1, x1_m=0, y1_m=4), Facing.X_MINUS),
    (Rect(x0_m=2, y0_m=6, x1_m=5, y1_m=9), Facing.Y_PLUS),
    (Rect(x0_m=2, y0_m=-3, x1_m=5, y1_m=0), Facing.Y_MINUS),
    (Rect(x0_m=11, y0_m=0, x1_m=13, y1_m=3), None),
])
def test_away_is_side_of_wing_from_shared_wall(wing, side):
    assert part_roofs.away(Rect(x0_m=0, y0_m=0, x1_m=10, y1_m=6), wing) is side


def probe():
    """Датчик ablation `tools/part_roofs_probe.py` как модуль."""
    path = Path(__file__).resolve().parents[2] / "tools" / "part_roofs_probe.py"
    spec = spec_from_file_location("part_roofs_probe", path)
    module = module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass ищет свой модуль в sys.modules
    spec.loader.exec_module(module)
    return module


def test_probe_reads_annex_as_shed_away_from_main_and_rule_agrees():
    (wing,) = probe().wings("l", walls(GABLE), RULE.annex_pitch_deg)
    assert wing.shed and wing.rule and wing.down_away and wing.attached
    assert wing.drop == pytest.approx(6.0 - 3.25) and wing.deep == pytest.approx(2.05 / 3)


def test_probe_threshold_is_learned_without_the_house_it_guesses():
    """Порог учится без дома, который угадывает: граница — посередине между соседними значениями;
    дом против общей границы (x) и тот, чья граница без него сдвигается (h2), — промахи."""
    p = probe()
    wing = partial(p.Wing, rule=False, down_away=False, attached=True, drop=0.0, deep=0.0,
                   share=0.0)
    same = [wing(house=f"h{i}", shed=a > 0.3, area=a) for i, a in enumerate((0.1, 0.2, 0.4, 0.5))]
    assert p.held_out(same) == len(same)
    odd = [*same, wing(house="x", shed=False, area=0.45)]
    assert p.held_out(odd) == len(same) - 1
