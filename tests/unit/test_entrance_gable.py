"""Щипец над входом по слову текста (gf#455, `facade: Щипец над карнизной стеной`,
`generation: Стаб шага 1`): слово ставит признак дому, шаг 3 строит щипец над стеной со входом."""

import pytest
from simple_house import SIMPLE

from genfacade import config, entrance_gable, pipeline, roof
from genfacade.models import stub
from genfacade.plan.preprocess import preprocess
from genfacade.schema import Mode, OpeningKind

CFG = config.load()
RULE = CFG.plan.parts
GABLE = "A house with a gable over the entrance. Gable roof."


def walls(text: str, rule=RULE):
    plan = preprocess(SIMPLE.read_text(), Mode.WITH_OPENINGS, CFG.plan)
    return pipeline.walls(stub.spec_model(text, CFG.models.spec), plan, rule)


def test_word_sets_the_feature_and_no_word_leaves_it_off():
    spec = CFG.models.spec
    assert stub.spec_model(GABLE, spec).gable_over_entrance
    assert stub.spec_model("Дом с фронтоном над входом", spec).gable_over_entrance
    assert stub.spec_model("Дом, крыльцо под фронтоном", spec).gable_over_entrance
    assert stub.spec_model("A cross gable house", spec).gable_over_entrance
    assert not stub.spec_model("A house. Gable roof.", spec).gable_over_entrance
    assert not stub.spec_model("A gable roof over the garage", spec).gable_over_entrance


def test_gable_stands_over_the_entrance_wall_when_the_text_names_it():
    """Лист со словом: щипец — на стене со входом, середина над серединой входа, внутри стены с
    отступом свеса; без слова щипца нет."""
    sheet = walls(GABLE)
    (g,) = sheet.wall_gables
    door = next(o for o in sheet.facades[g.side].side.openings if o.kind is OpeningKind.ENTRANCE)
    assert (g.x0_m + g.x1_m) / 2 == pytest.approx(door.x_m + door.width_m / 2, abs=0.01)
    assert g.x1_m - g.x0_m == pytest.approx(RULE.entrance_gable_share * 10.0, abs=0.01)
    assert g.pitch_deg == RULE.entrance_gable_pitch_deg
    assert len(roof.roofs(sheet).parts) == len(roof.roofs(walls("A house. Gable roof.")).parts) + 1
    assert not walls("A house. Gable roof.").wall_gables


@pytest.mark.parametrize("kind", ["Hip roof", "Flat roof", "Shed roof"])
def test_feature_is_ignored_for_other_roofs(kind):
    assert not walls(f"A house with a gable over the entrance. {kind}.").wall_gables


def test_without_the_generation_rule_the_feature_is_not_read():
    """Синтетика и разметка вызывают развёртку без правила: щипец у них свой."""
    assert not walls(GABLE, rule=None).wall_gables


def test_synthetic_and_generation_share_one_function():
    """Одна функция на синтетику и на генерацию: тот же щипец при тех же ширине и уклоне."""
    sheet = walls("A house. Gable roof.")
    by_rule = entrance_gable.chosen(
        sheet.model_copy(update={"spec": sheet.spec.model_copy(
            update={"gable_over_entrance": True})}), RULE)
    direct = entrance_gable.placed(sheet, RULE.entrance_gable_share,
                                   RULE.entrance_gable_pitch_deg, RULE.entrance_gable_min_m)
    assert by_rule.wall_gables == direct.wall_gables != []
