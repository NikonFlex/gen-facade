"""Крыша дома (gf#320, `facade: Скатная крыша над прямоугольным домом`): скаты — нижняя огибающая
плоскостей от карнизных стен; фронтон и кровля на виде — из неё, на углах высоты сходятся."""

import math

import pytest
import shapely
from roof_cover import projection, uncovered
from simple_house import L_SHAPE, SIMPLE

from genfacade import config, pipeline, roof
from genfacade.models import stub
from genfacade.plan.preprocess import preprocess
from genfacade.render.svg import sheet_svg
from genfacade.schema import (
    Element,
    ElementClass,
    Facing,
    Mode,
    Roof,
    RoofKind,
    Rule,
    WallGable,
)
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


def test_flat_house_and_l_shaped_house_have_no_single_roofline(simple_svg):
    """Плоская — скатов нет; у Г-образного дома нет одной крыши на все стены — она по крыльям
    (`roofs`), и предупреждения нет (gf#431, этап В); плоская над Г — нечего предупреждать."""
    assert roof.roofline(bare(RoofKind.FLAT)) is None
    l_house = bare(RoofKind.GABLE, simple_svg(*L_SHAPE))
    assert roof.roofline(l_house) is None and roof.roofs(l_house) is not None
    assert not [v for v in validate(l_house, CFG.checks) if v.rule is Rule.ROOF_FLAT]
    flat = bare(RoofKind.FLAT, simple_svg(*L_SHAPE))
    assert roof.roofs(flat) is None
    assert not [v for v in validate(flat, CFG.checks) if v.rule is Rule.ROOF_FLAT]


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


# ——— Щипец над карнизной стеной (gf#431, `facade: Щипец над карнизной стеной`) ———


def gabled(pitch: float, *, end: bool = False, kind: RoofKind = RoofKind.GABLE):
    """Простой дом с крышей вида kind и щипцом 2 м посередине карнизной стены (end — без карниза);
    лист, номер стены и глубина дома поперёк неё."""
    sheet = bare(kind)
    eaves = roof.eave_walls(sheet)
    k = next(k for k in range(4) if (k in eaves) != end)
    length = sheet.facades[k].side.length_m
    gable = WallGable(side=k, x0_m=length / 2 - 1, x1_m=length / 2 + 1, pitch_deg=pitch)
    return sheet.model_copy(update={"wall_gables": [gable]}), k, sheet.facades[k - 1].side.length_m


def visible(house: roof.HouseRoof, zone) -> list[tuple[float, float, float]]:
    """Вершины граней обеих кровель внутри зоны продолжения."""
    return [(x, y, z) for k in range(len(house.parts)) for _, f in roof._part_faces(house, k)
            for x, y, z in f if zone.buffer(-1e-3).contains(shapely.Point(x, y))]


def test_wall_gable_runs_from_the_wall_to_the_ridge():
    """Щипец 2 м под 45° на карнизной стене: на стене — треугольник до карниза + 1 м над серединой
    участка, на листе кровля его не закрывает; кровля щипца идёт от стены над скатом дома до конька
    (глубина — половина дома), свес дома под щипцом прерван; в зоне видна более высокая кровля,
    дыр в крыше нет."""
    sheet, k, depth = gabled(45.0)
    house = roof.roofs(sheet)
    (ext,) = house.extensions
    assert (ext.part, ext.into) == (1, 0) and len(house.parts) == 2
    x0, y0, x1, y1 = ext.zone.bounds  # до конька и полоса свеса перед стеной
    overhang = sheet.spec.roof.overhang_m
    assert sorted([x1 - x0, y1 - y0]) == pytest.approx(sorted([2.0, depth / 2 + overhang]))
    eaves = sheet.spec.eaves_m
    (above,) = roof.house_above(house, k)
    assert max(y for _, y in above) == pytest.approx(eaves + 1.0)
    view = shapely.union_all([shapely.Polygon(p) for p in roof.house_view(house, k, 0.1)])
    assert shapely.Polygon(above).intersection(view).area == pytest.approx(0.0, abs=1e-9)
    parts = house.parts
    seen = visible(house, ext.zone)
    assert seen and all(z == pytest.approx(max(p.height((x, y)) for p in parts), abs=1e-6)
                        for x, y, z in seen)
    assert uncovered(house) == pytest.approx(0.0, abs=1e-9)


def test_wall_gable_roof_has_no_side_overhang_below_the_house_eave():
    """Кровля щипца 53° не выходит за края участка (gf#431, снимок хозяина 11.11 — «плавники»):
    за краями её свес висел бы под кромкой свеса дома 35°; ни одна её вершина не ниже карниза."""
    sheet, _, _ = gabled(53.0)
    house = roof.roofs(sheet)
    (ext,) = house.extensions
    eaves = sheet.spec.eaves_m
    found = [p for _, f in roof._part_faces(house, ext.part) for p in f]
    assert found and min(z for _, _, z in found) == pytest.approx(eaves)
    union = shapely.union_all([shapely.Polygon([(x, y) for x, y, _ in f])
                               for _, f in roof._part_faces(house, ext.part)])
    assert union.difference(ext.zone).area == pytest.approx(0.0, abs=1e-9)
    assert uncovered(house) == pytest.approx(0.0, abs=1e-9)


def test_wall_gable_above_the_ridge_stops_at_it():
    """Щипец круче, чем позволяет конёк дома, — до конька: его вершина на высоте конька."""
    sheet, k, depth = gabled(80.0)
    house = roof.roofs(sheet)
    assert len(house.parts) == 2
    top = max(z for _, f in roof._part_faces(house, 1) for *_, z in f)
    assert top == pytest.approx(ridge(sheet, depth))


def test_wall_gable_on_shed_runs_up_to_the_high_wall():
    """У односкатной скат поднимается от низкой стены до высокой — щипец на низкой идёт через весь
    дом."""
    sheet, k, depth = gabled(30.0, kind=RoofKind.SHED)
    (ext,) = roof.roofs(sheet).extensions
    x0, y0, x1, y1 = ext.zone.bounds
    overhang = sheet.spec.roof.overhang_m
    assert sorted([x1 - x0, y1 - y0]) == pytest.approx(sorted([2.0, depth + overhang]))


def test_sheet_gables_add_the_wall_gable_zone_and_keep_the_model_ones():
    """Зона фронтона листа у стены со щипцом — его треугольник (окно мансарды стоит в нём), у
    остальных сторон — как у модели (`roof.gables`: условие шага 4 щипца над стеной не видит)."""
    sheet, k, _ = gabled(45.0)
    assert roof.gables(sheet) == roof.gables(sheet.model_copy(update={"wall_gables": []}))
    assert roof.gables(sheet)[k] is None
    zones = roof.sheet_gables(sheet)
    assert zones[k] is not None and max(y for _, y in zones[k]) == pytest.approx(
        sheet.spec.eaves_m + 1.0)
    assert [z for i, z in enumerate(zones) if i != k] == [
        z for i, z in enumerate(roof.gables(sheet)) if i != k]


def test_wall_gable_on_a_gable_end_is_not_built():
    """На торцевой стене скат дома от стены не поднимается — щипцу некуда идти."""
    sheet, _, _ = gabled(45.0, end=True)
    assert len(roof.roofs(sheet).parts) == 1


def test_wall_gable_must_stand_on_the_wall():
    sheet, k, _ = gabled(45.0)
    length = sheet.facades[k].side.length_m
    with pytest.raises(ValueError, match="x"):
        WallGable(side=k, x0_m=2.0, x1_m=2.0, pitch_deg=45.0)
    data = sheet.model_dump() | {"wall_gables": [{"side": k, "x0_m": 1.0, "x1_m": length + 1,
                                                  "pitch_deg": 45.0}]}
    with pytest.raises(ValueError, match="не на стене"):
        type(sheet).model_validate(data)



# ——— Г-, Т-, П-дом одной высоты (gf#431, этап В) ———

WALL_M = 0.15  # толщина стены плана, как в simple_house.svg
PX_PER_M = 100
DOOR_PX = 90  # ширина входной двери плана, как у simple_house.svg

# Г: крыло 10 × 6 м и крыло 4 × 4 м у его длинной стены, у края; Т — то же посреди стены;
# П — крыло 10 × 4 м и два крыла 3 × 4 м по его краям
L_HOUSE = [(1, 1), (11, 1), (11, 11), (7, 11), (7, 7), (1, 7)]
T_HOUSE = [(1, 1), (11, 1), (11, 7), (8, 7), (8, 11), (4, 11), (4, 7), (1, 7)]
U_HOUSE = [(1, 1), (11, 1), (11, 9), (8, 9), (8, 5), (4, 5), (4, 9), (1, 9)]


def outline_svg(outline: list[tuple[float, float]]) -> str:
    """План по ортогональному контуру в метрах: стена каждой стороны — прямоугольник толщиной
    WALL_M внутрь контура (контур плана — внешняя грань стен, как у simple_house.svg); в середине
    первой стороны (горизонтальной, y = const) — входная дверь: разрыв, створка и дуга, как на
    плане GenPlan, без входа план не читается."""
    shape = shapely.Polygon(outline)
    ring = list(shape.exterior.coords)
    strips = [shapely.LineString([a, b]).buffer(WALL_M, cap_style="square").intersection(shape)
              for a, b in zip(ring, ring[1:], strict=False)]
    (x0, y0), (x1, _) = ring[0], ring[1]
    left, right = (round(((x0 + x1) / 2) * PX_PER_M) + sign * DOOR_PX // 2 for sign in (-1, 1))
    wall_y = round(y0 * PX_PER_M)
    gap = shapely.box(left / PX_PER_M, y0 - 1, right / PX_PER_M, y0 + 1)
    cut = [strip.difference(gap) for strip in strips]
    pieces = [g for c in cut for g in getattr(c, "geoms", [c])
              if isinstance(g, shapely.Polygon) and g.area > 0]
    rects = [tuple(round(v * PX_PER_M) for v in g.bounds) for g in pieces]
    body = "".join(f'<rect x="{x}" y="{y}" width="{xe - x}" height="{ye - y}" fill="#000000" />'
                   for x, y, xe, ye in rects)
    door = (f'<rect x="{left}" y="{wall_y + WALL_M * PX_PER_M:.0f}" width="5" height="{DOOR_PX}" '
            'fill="#000000" />'
            f'<path d="M{right},{wall_y + WALL_M * PX_PER_M:.0f} A{DOOR_PX},{DOOR_PX},0,0,1,'
            f'{left},{wall_y + WALL_M * PX_PER_M + DOOR_PX:.0f}" stroke="#000000" fill="none" '
            'stroke-width="5" />')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="1200" '
            f'viewBox="0 0 1400 1200">{body}{door}</svg>')


def wing_house(outline: list[tuple[float, float]], kind: RoofKind = RoofKind.GABLE):
    """Лист дома одной высоты по контуру outline и его крыша по крыльям."""
    sheet = bare(kind, outline_svg(outline))
    return sheet, roof.roofs(sheet)


def test_l_house_of_one_height_has_roof_over_each_wing():
    """Г-дом одной высоты: скат у каждого крыла; конёк крыла 4 × 4 — поперёк главного, его кровля
    продолжена над главным до его конька, стенки на общей линии нет (gf#431, этап В)."""
    sheet, house = wing_house(L_HOUSE)
    assert [f.runs for f in sheet.facades] == [[]] * 6 and len(sheet.wings) == 2
    main, wing = sorted(range(2), key=lambda k: -shapely.Polygon(house.parts[k].corners).area)
    assert {abs(s.inward[1]) for s in house.parts[main].slopes} == {1.0}  # конёк вдоль x
    assert {abs(s.inward[0]) for s in house.parts[wing].slopes} == {1.0}  # конёк вдоль y
    assert all(line.eaves == sheet.spec.eaves_m for line in house.parts)
    (ext,) = house.extensions
    assert (ext.part, ext.into) == (wing, main)
    assert roof.joints(house) == []
    assert uncovered(house) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize("outline", [T_HOUSE, U_HOUSE], ids=["T", "U"])
def test_t_and_u_houses_of_one_height_are_roofed_without_holes(outline):
    sheet, house = wing_house(outline)
    assert len(house.parts) >= 2 and all(line.slopes for line in house.parts)
    assert uncovered(house) == pytest.approx(0.0, abs=1e-6)
    reach = shapely.Polygon(house.corners).buffer(house.parts[0].overhang + 1e-6,
                                                  join_style="mitre")
    assert projection(house).difference(reach).area == pytest.approx(0.0, abs=1e-6)


def test_wing_house_with_pitched_roof_has_no_roof_flat_warning():
    """`Rule.ROOF_FLAT` — только когда скатная крыша над непрямоугольным контуром не строится
    (gf#431, этап В)."""
    sheet, house = wing_house(L_HOUSE)
    assert roof.roofline(sheet) is None and house is not None
    assert Rule.ROOF_FLAT not in {v.rule for v in validate(sheet, CFG.checks)}


def test_skewed_contour_keeps_roof_flat_warning():
    """Контур, что не делится на крылья (сторона повёрнута не на 90°), — скатов нет, у скатной
    крыши предупреждение `Rule.ROOF_FLAT` (`evaluation: Скатная крыша над непрямоугольным
    домом`)."""
    sheet, _ = wing_house(L_HOUSE)
    f = sheet.facades[1]
    turn = math.radians(20)
    (nx, ny) = f.side.orientation
    skew = f.model_copy(update={"side": f.side.model_copy(update={"orientation": (
        nx * math.cos(turn) - ny * math.sin(turn), nx * math.sin(turn) + ny * math.cos(turn))})})
    skewed = sheet.model_copy(update={"wings": [], "facades": [
        skew if k == 1 else g for k, g in enumerate(sheet.facades)]})
    assert roof.roofs(skewed) is None
    assert Rule.ROOF_FLAT in {v.rule for v in validate(skewed, CFG.checks)}


def test_part_rank_is_eaves_then_area_then_number():
    """Старшинство частей: карниз, площадь крыла, меньший номер; при разном карнизе площадь не
    считается — как было у частей разной высоты."""
    rank = roof._rank
    assert roof._outranks(rank(6.0, 1.0, 5), rank(3.0, 99.0, 0))
    assert roof._outranks(rank(3.0, 8.0, 5), rank(3.0, 2.0, 0))
    assert roof._outranks(rank(3.0, 2.0, 0), rank(3.0, 2.0, 1))
    assert not roof._outranks(rank(3.0, 2.0, 1), rank(3.0, 2.0, 0))
    assert not roof._outranks(rank(3.0, 2.0, 0), rank(3.0, 2.0, 0))


def sorted_faces(house) -> list:
    return sorted([tuple(round(v, 6) for p in face for v in p) for face in roof.house_faces(house)])


def test_wing_roof_does_not_depend_on_wing_numbers():
    """Кто главнее при равном карнизе — по площади крыла, а не по номеру в листе (gf#431, этап В):
    те же крылья в обратном порядке дают те же грани и ту же кровлю над общей линией."""
    sheet, house = wing_house(L_HOUSE)
    turned = sheet.model_copy(update={"wings": sheet.wings[::-1]})
    back = roof.roofs(turned)
    assert sorted_faces(back) == sorted_faces(house)
    assert [(e.part, e.into) for e in back.extensions] == [(0, 1)]
    assert uncovered(back) == pytest.approx(0.0, abs=1e-6)


def test_wing_with_higher_ridge_than_main_has_gable_wall_over_the_main_roof():
    """Над общей линией крыла и главного крыла одного карниза нет продолжения, когда конёк крыла
    выше конька главного (крутой скат): стена щипца крыла над кровлей главного — примыкание
    (gf#431, этап В, пары равного карниза)."""
    sheet, _ = wing_house(L_HOUSE)
    steep = sheet.spec.roof.model_copy(update={"pitch_deg": 70.0})
    sheet = sheet.model_copy(update={"roofs": [sheet.spec.roof, steep]})
    house = roof.roofs(sheet)
    assert house.extensions == ()
    (joint,) = roof.joints(house)
    assert joint.high == 1 and joint.walls and min(z for w in joint.walls for *_, z in w) >= (
        sheet.spec.eaves_m - 1e-6)


# ——— Свес карнизный и фронтонный (gf#451, `facade: Свес карнизный и фронтонный`) ———


def plan_extent(line: roof.Roofline) -> tuple[float, float]:
    """Размеры кровли в плане (x, y) — габарит союза её граней."""
    area = shapely.union_all([shapely.Polygon([(x, y) for x, y, _ in f])
                              for _, f in roof.faces(line)])
    x0, y0, x1, y1 = area.bounds
    return x1 - x0, y1 - y0


def house_10x6(eave: float, gable: float) -> roof.Roofline:
    """Дом 10 × 6, двускатная 35°, конёк вдоль длинной стороны: карнизы на длинных сторонах."""
    corners = [(0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)]
    slopes = [roof.Slope(corners[0], (0.0, 1.0)), roof.Slope(corners[2], (0.0, -1.0))]
    return roof.Roofline(corners, slopes, 3.0, math.tan(math.radians(35)), eave, gable)


def test_gable_roof_hangs_over_eave_and_gable_walls_by_their_own_overhang():
    assert plan_extent(house_10x6(0.5, 0.0)) == pytest.approx((10.0, 7.0))
    assert plan_extent(house_10x6(0.0, 0.5)) == pytest.approx((11.0, 6.0))
    assert plan_extent(house_10x6(0.5, 0.3)) == pytest.approx((10.6, 7.0))


def test_roof_without_gable_overhang_hangs_as_before():
    """Фронтонный не задан — равен карнизному: контур с одним свесом по всем сторонам."""
    assert Roof(kind=RoofKind.GABLE, pitch_deg=35, overhang_m=0.5).gable_overhang == 0.5
    sheet = bare(RoofKind.GABLE)
    plain = sheet.spec.roof.model_copy(update={"overhang_m": 0.5, "gable_overhang_m": None})
    same = plain.model_copy(update={"gable_overhang_m": 0.5})
    extents = [plan_extent(_line_with(sheet, r)) for r in (plain, same)]
    line = _line_with(sheet, same)
    xs = [c[0] for c in line.corners]
    ys = [c[1] for c in line.corners]
    assert extents[0] == pytest.approx(extents[1])
    assert extents[0] == pytest.approx((max(xs) - min(xs) + 1.0, max(ys) - min(ys) + 1.0))


def _line_with(sheet, r: Roof) -> roof.Roofline:
    """Скаты листа с крышей r вместо его крыши."""
    return roof.roofline(sheet.model_copy(update={"spec": sheet.spec.model_copy(
        update={"roof": r})}))


def test_hip_roof_ignores_gable_overhang():
    sheet = bare(RoofKind.HIP)
    extents = [plan_extent(_line_with(sheet, sheet.spec.roof.model_copy(
        update={"overhang_m": 0.5, "gable_overhang_m": gable}))) for gable in (None, 0.9)]
    assert extents[0] == pytest.approx(extents[1])
