"""Крыша дома (gf#320, `facade: Скатная крыша над прямоугольным домом`): скаты — нижняя огибающая
плоскостей от карнизных стен; фронтон и кровля на виде — из неё, на углах высоты сходятся."""

import math

import pytest
import shapely
from simple_house import L_SHAPE, SIMPLE

from genfacade import config, pipeline, roof
from genfacade.models import stub
from genfacade.plan.preprocess import preprocess
from genfacade.render.svg import sheet_svg
from genfacade.schema import Element, ElementClass, Facing, Mode, Roof, RoofKind, Rule
from genfacade.unfold import unfold
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


def ridge(sheet, span: float) -> float:
    """Конёк двускатной над карнизом дома: половина пролёта span на подъём ската."""
    return sheet.spec.eaves_m + span / 2 * rise(RoofKind.GABLE)


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
            assert max(y for _, y in shape) == pytest.approx(ridge(sheet, span))
            apex = max(shape, key=lambda p: p[1])
            assert apex[0] == pytest.approx(length / 2)


def directed(kind: RoofKind, k: int):
    """Простой дом с крышей вида kind, скат которой спускается к стороне k листа."""
    sheet = bare(kind)
    to = Facing.of(sheet.facades[k].side.orientation)
    house_roof = sheet.spec.roof.model_copy(update={"down_to": to})
    spec = sheet.spec.model_copy(update={"roof": house_roof})
    return sheet.model_copy(update={"spec": spec})


def test_gable_with_direction_has_eaves_where_it_points():
    """`facade: Направление ската`, «Двускатная с коньком поперёк»: направление на короткую стену —
    карнизы на коротких, фронтоны на длинных, конёк на половине длинной стороны."""
    sides = [f.side for f in bare(RoofKind.GABLE).facades]
    short = min(range(4), key=lambda k: sides[k].length_m)
    sheet = directed(RoofKind.GABLE, short)
    line = roof.roofline(sheet)
    span = max(s.length_m for s in sides)
    for k in range(4):
        shape = roof.above_eaves(line, k)
        assert (shape is None) if k % 2 == short % 2 else (
            max(y for _, y in shape) == pytest.approx(ridge(sheet, span)))
    assert roof.eave_walls(sheet) == {short, (short + 2) % 4}


def test_shed_with_direction_is_low_where_it_points():
    """Направление односкатной — против правила входа: низ на стене напротив входа."""
    sides = [f.side for f in bare(RoofKind.SHED).facades]
    entrance = next(k for k, s in enumerate(sides) if s.has_entrance)
    low = (entrance + 2) % 4
    line = roof.roofline(directed(RoofKind.SHED, low))
    assert roof.above_eaves(line, low) is None and roof.above_eaves(line, entrance) is not None


def test_direction_only_for_gable_and_shed():
    with pytest.raises(ValueError, match="направления ската у неё нет"):
        Roof(kind=RoofKind.HIP, pitch_deg=25.0, down_to=Facing.X_PLUS)
    assert Facing.of((0.0, -0.9999)) is Facing.Y_MINUS


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


def test_window_room_keeps_off_the_slope():
    """Место окна во фронтоне (gf#321): стена с фронтоном без полосы `slope_offset_m` у ската —
    рамка с отступом 0,3 м годна, с отступом 0,1 м и через скат — нет."""
    above = [(0.0, 3.0), (3.0, 5.0), (6.0, 3.0)]  # щипец 6 м, конёк на 2 м выше карниза
    room = roof.room(6.0, 3.0, above, 0.2)
    cos = 3.0 / math.hypot(3.0, 2.0)  # высота над рамкой → расстояние до ската

    def at(gap: float) -> shapely.Geometry:  # окно 1 × 1 м у левого ската, отступ gap
        x = 1.5
        top = 3.0 + x * 2.0 / 3.0 - gap / cos
        return shapely.box(x, top - 1.0, x + 1.0, top)

    assert room.contains(at(0.3))
    assert not room.contains(at(0.1))
    assert not room.contains(at(-0.2))
    assert roof.peaks(above, 3.0) == [(3.0, 5.0)]
    assert roof.wall_shape(6.0, 3.0, above).area == pytest.approx(6.0 * 3.0 + 6.0)


def _with_window(sheet, k: int, x: float, y: float, w: float, h: float):
    window = Element(id="g1", cls=ElementClass.WINDOW, x_m=x, y_m=y, w_m=w, h_m=h,
                     floor=sheet.spec.floors + 1)
    facades = list(sheet.facades)
    facades[k] = facades[k].model_copy(update={"elements": [window]})
    return sheet.model_copy(update={"facades": facades})


def test_validator_keeps_gable_window_off_the_slope():
    """`evaluation: Ошибки геометрии` (gf#321): окно во фронтоне — в стене с фронтоном и не ближе
    `slope_offset_m` к скату: годное — без нарушений, у ската — `slope`, через скат — ещё и
    `outside`; на карнизной стене выше карниза — `outside`."""
    sheet = unfold(bare(RoofKind.GABLE))
    gables = roof.gables(sheet)
    k = next(i for i, a in enumerate(gables) if a is not None)
    eave = next(i for i, a in enumerate(gables) if a is None)
    length, eaves = sheet.facades[k].side.length_m, sheet.spec.eaves_m
    rules = lambda s: {v.rule for v in validate(s, CFG.checks)  # noqa: E731
                       if v.rule in (Rule.SLOPE, Rule.OUTSIDE)}
    mid = length / 2
    assert rules(_with_window(sheet, k, mid - 0.3, eaves + 0.1, 0.6, 0.6)) == set()
    near = eaves + (mid - 0.3) * rise(RoofKind.GABLE) - 0.6  # верх угла рамки на скате
    assert rules(_with_window(sheet, k, mid - 0.3, near, 0.6, 0.6 - 0.05)) == {Rule.SLOPE}
    assert rules(_with_window(sheet, k, 0.2, eaves + 0.1, 0.6, 0.6)) == {Rule.SLOPE, Rule.OUTSIDE}
    assert Rule.OUTSIDE in rules(_with_window(sheet, eave, 1.0, eaves + 0.1, 0.6, 0.6))


class Ramp:
    """Кровля-заглушка: высота растёт вдоль x от `base` с уклоном `rise`, плоская при rise = 0."""

    def __init__(self, eaves: float, base: float, rise: float, corners):
        self.eaves, self.base, self.rise, self.corners, self.slopes = eaves, base, rise, corners, []

    def height(self, p) -> float:
        return self.base + self.rise * p[0]


def test_joint_wall_stands_on_the_part_whose_roof_is_higher():
    """Разрез по ступени карниза (gf#422): у нижней по карнизу части щипец выше кровли верхней —
    над кровлей верхней стоит стена нижней (обратная нормаль), а не пустое небо; там, где кровля
    верхней выше, стена её, как раньше."""
    high = Ramp(5.0, 5.0, 0.0, [(0, 0), (6, 0), (6, 4), (0, 4)])  # плоская кровля на 5 м
    low = Ramp(4.0, 4.0, 0.5, [(0, -3), (6, -3), (6, 0), (0, 0)])  # от 4 м, у x = 6 — 7 м
    owned = roof._joint(low, high, 1, [(0.0, 0.0), (6.0, 0.0)], 0)
    by_high = {j.high: j for j in owned}
    assert set(by_high) == {0, 1}
    assert by_high[1].normal == pytest.approx((0.0, -1.0))  # от верхней к нижней
    assert by_high[0].normal == pytest.approx((0.0, 1.0))  # стена нижней — наружу к верхней
    assert max(z for w in by_high[0].walls for *_, z in w) == pytest.approx(7.0)
    assert min(z for w in by_high[0].walls for *_, z in w) == pytest.approx(5.0)
    assert max(z for w in by_high[1].walls for *_, z in w) == pytest.approx(5.0)
    assert {round(x, 6) for w in by_high[0].walls for x, *_ in w} == {2.0, 6.0}  # от пересечения
