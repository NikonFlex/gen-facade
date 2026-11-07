"""Крыша дома (gf#320, `facade: Скатная крыша над прямоугольным домом`): скаты — нижняя огибающая
плоскостей от карнизных стен; фронтон и кровля на виде — из неё, на углах высоты сходятся."""

import math

import pytest
from simple_house import L_SHAPE, SIMPLE

from genfacade import config, pipeline, roof
from genfacade.models import stub
from genfacade.plan.preprocess import preprocess
from genfacade.render.svg import sheet_svg
from genfacade.schema import Mode, RoofKind, Rule
from genfacade.validate import validate

CFG = config.load()
PITCH = CFG.models.spec.roof_shape.pitch_deg


def bare(kind: RoofKind, svg: str | None = None):
    """Стены простого дома (или плана svg) с крышей вида kind."""
    spec = stub.spec_model("", CFG.models.spec)
    spec = spec.model_copy(update={"roof": CFG.models.spec.roof_shape.roof(kind, "roof")})
    plan = preprocess(svg or SIMPLE.read_text(), Mode.WITH_OPENINGS, CFG.plan)
    return pipeline.walls(spec, plan)


def rise(kind: RoofKind) -> float:
    return math.tan(math.radians(PITCH[kind]))


def corner_heights(line: roof.Roofline, k: int) -> tuple[float, float]:
    """Высота верха стены k над её левым и правым краем: стена над карнизом или карниз."""
    shape = roof.above_eaves(line, k)
    if shape is None:
        return line.eaves, line.eaves
    _, _, length = roof.wall_axis(line, k)
    return (max(y for x, y in shape if x <= 1e-9),
            max(y for x, y in shape if x >= length - 1e-9))


@pytest.mark.parametrize("kind", [RoofKind.GABLE, RoofKind.HIP, RoofKind.SHED])
def test_walls_meet_at_corners(kind):
    """Верх соседних стен над общим углом одной высоты: правый край стены k — угол k, левый край
    стены k−1 — тоже угол k (`facade: Углы сходятся`)."""
    line = roof.roofline(bare(kind))
    for k in range(4):
        assert corner_heights(line, k)[1] == pytest.approx(corner_heights(line, k - 1)[0])


def test_gable_has_gables_on_short_walls():
    sheet = bare(RoofKind.GABLE)
    line = roof.roofline(sheet)
    lengths = [f.side.length_m for f in sheet.facades]
    span = min(lengths)
    for k, length in enumerate(lengths):
        shape = roof.above_eaves(line, k)
        if length > span:
            assert shape is None  # длинная стена — карнизная
        else:  # фронтон: конёк над серединой короткой стены
            assert max(y for _, y in shape) == pytest.approx(
                sheet.spec.eaves_m + span / 2 * rise(RoofKind.GABLE))
            apex = max(shape, key=lambda p: p[1])
            assert apex[0] == pytest.approx(length / 2)


def test_hip_slopes_from_all_walls():
    sheet = bare(RoofKind.HIP)
    line = roof.roofline(sheet)
    assert all(roof.above_eaves(line, k) is None for k in range(4))
    assert len(roof.faces(line)) == 4


def test_shed_is_low_at_the_entrance():
    """Односкатная: низ у длинной стены со входом, напротив — стена выше карниза на всю длину;
    кровля на высокой стороне — только кромка над стеной: скат уходит за стену."""
    sheet = bare(RoofKind.SHED)
    line = roof.roofline(sheet)
    sides = [f.side for f in sheet.facades]
    span = min(s.length_m for s in sides)
    low = next(k for k, s in enumerate(sides) if s.has_entrance)
    high = (low + 2) % 4
    assert roof.above_eaves(line, low) is None
    top = sheet.spec.eaves_m + span * rise(RoofKind.SHED)
    assert max(y for _, y in roof.above_eaves(line, high)) == pytest.approx(top)
    view = roof.roof_view(line, high, CFG.sheet.roof.thickness_m)
    assert min(y for shape in view for _, y in shape) >= top - 1e-6


def test_flat_and_l_shaped_houses_have_no_slopes(simple_svg):
    """Плоская — скатов нет; скатная над Г-образным планом пока не строится — предупреждение."""
    assert roof.roofline(bare(RoofKind.FLAT)) is None
    l_house = bare(RoofKind.GABLE, simple_svg(*L_SHAPE))
    assert roof.roofline(l_house) is None
    warned = [v for v in validate(l_house, CFG.checks) if v.rule is Rule.ROOF_FLAT]
    assert len(warned) == 1 and warned[0].severity == "warning"
    assert not [v for v in validate(bare(RoofKind.GABLE), CFG.checks) if v.rule is Rule.ROOF_FLAT]


def test_sheet_draws_roof_and_gables():
    svg = sheet_svg(bare(RoofKind.GABLE), CFG)
    assert svg.count('class="roof"') >= 4 and svg.count('class="above-eaves"') == 2
    assert 'class="roof"' not in sheet_svg(bare(RoofKind.FLAT), CFG)


@pytest.mark.parametrize(("text", "kind"), [
    ("A brick cottage with a gable roof.", RoofKind.GABLE),
    ("Дом с вальмовой крышей", RoofKind.HIP),
    ("A modern house with a shed roof", RoofKind.SHED),
    ("A simple one-storey house with a flat roof.", RoofKind.FLAT),
])
def test_stub_takes_roof_from_text(text, kind):
    """Стаб шага 1: вид крыши — по слову текста, уклон и свес — по виду из настроек."""
    got = stub.spec_model(text, CFG.models.spec).roof
    assert got.kind is kind
    assert got.pitch_deg == PITCH.get(kind, 0.0)


def test_stub_roof_without_words_is_the_finish_roof():
    rules = CFG.models.spec
    spec = stub.spec_model("", rules)
    assert spec.roof.kind is rules.finish[rules.default_finish].roof
