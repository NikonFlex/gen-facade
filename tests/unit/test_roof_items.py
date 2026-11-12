"""Дымовая труба и водосток (gf#454, `facade: Дымовая труба`, `facade: Водосток`,
`generation: Труба и водосток по словам текста`): кодом на листе, в 3D и IFC; модель их не видит."""

import math

import pytest
import shapely
import vocab
from simple_house import L_SHAPE
from test_manual import PT, finished

from genfacade import config, pipeline, roof, roof_items
from genfacade.datasets import manual
from genfacade.datasets.manual import BadMarkup, Markup
from genfacade.models import stub
from genfacade.parts import Span
from genfacade.plan.preprocess import preprocess
from genfacade.render.house3d import house_3d
from genfacade.render.ifc import counts, house_ifc
from genfacade.render.svg import sheet_svg
from genfacade.roof_items import ItemKind
from genfacade.schema import Mode, RoofKind
from genfacade.train import tokens

CFG = config.load()
LOOK = CFG.sheet.roof_items
SPEC = CFG.models.spec
PITCH35 = math.tan(math.radians(35))
CORNERS = [(0.0, 6.0), (10.0, 6.0), (10.0, 0.0), (0.0, 0.0)]  # по часовой, как контур дома


def _house(slopes: list[roof.Slope], eave: float, gable: float) -> roof.HouseRoof:
    """Дом 10 × 6 м со скатами slopes 35°, карниз 3,25 м, одна часть."""
    line = roof.Roofline(CORNERS, slopes, 3.25, PITCH35, eave, gable)
    return roof.HouseRoof(CORNERS, [line], [[Span(0.0, 10.0, 0)] for _ in CORNERS])


def gable_house(eave: float = 0.5, gable: float = 0.3) -> roof.HouseRoof:
    """Дом 10 × 6 м, двускатная 35°, карниз 3,25 м, конёк 5,35 м вдоль длинной стороны."""
    return _house([roof.Slope(CORNERS[0], (0.0, -1.0)), roof.Slope(CORNERS[2], (0.0, 1.0))],
                  eave, gable)


def shed_house() -> roof.HouseRoof:
    """Односкатная: низ у стороны y = 0, высокая стена — y = 6."""
    return _house([roof.Slope(CORNERS[2], (0.0, 1.0))], 0.5, 0.3)


def hip_house() -> roof.HouseRoof:
    slopes = [roof.Slope(CORNERS[0], (0.0, -1.0)), roof.Slope(CORNERS[1], (-1.0, 0.0)),
              roof.Slope(CORNERS[2], (0.0, 1.0)), roof.Slope(CORNERS[3], (1.0, 0.0))]
    return _house(slopes, 0.5, 0.5)


def test_chimney_at_ridge():
    """Сценарий «Труба у конька»: центр в 2,5 м от начала конька, верх 5,85 м, сечение 0,51 м,
    низ — внутри кровли (ниже конька)."""
    found = roof_items.of_house(gable_house(), 0.25, False, LOOK).chimney
    xs, ys = [p[0] for p in found.footprint], [p[1] for p in found.footprint]
    assert (min(xs) + max(xs)) / 2 == pytest.approx(2.5)  # начало конька — (0, 3)
    assert (min(ys) + max(ys)) / 2 == pytest.approx(3.0)
    assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx((0.51, 0.51))
    assert found.z1 == pytest.approx(5.85, abs=0.01)
    assert 5.35 - PITCH35 * 0.255 - 0.01 <= found.z0 < 5.35


def test_ridge_starts_at_corner_zero():
    """Начало конька — конец, ближний к углу 0 контура части; доля считается от него."""
    line = gable_house().parts[0]
    a, b, top = roof_items.ridge(line)
    assert (a, b) == ((0.0, 3.0), (10.0, 3.0)) and top == pytest.approx(5.35, abs=0.01)
    far = roof.Roofline(line.corners[2:] + line.corners[:2], line.slopes, 3.25, PITCH35, 0.5, 0.3)
    assert roof_items.ridge(far)[0] == (10.0, 3.0)


def test_chimney_on_shed_at_high_side():
    """Односкатная: труба у высокой стороны, внутри контура, верх — высота высокой кромки + 0,5."""
    found = roof_items.of_house(shed_house(), 0.5, False, LOOK).chimney
    high = 3.25 + 6 * PITCH35
    assert found.z1 == pytest.approx(high + 0.5)
    assert all(0 <= x <= 10 and 5.49 - 1e-9 <= y <= 6.0 + 1e-9 for x, y in found.footprint)


def test_flat_roof_has_no_chimney_and_no_gutters(house):
    flat = house.model_copy(update={"spec": house.spec.model_copy(update={
        "roof": SPEC.roof_shape.roof(RoofKind.FLAT, "roof"), "chimney": 0.25, "gutters": True})})
    assert roof_items.roof_items(flat, LOOK) == roof_items.Items(None, [], [])


def test_gutters_along_eaves_and_pipe_at_each_end():
    """Сценарий «Водосток двускатного дома»: два желоба по 10 м + свесы фронтонов вдоль длинных
    сторон по краю свеса, четыре трубы у углов на стене, до земли."""
    found = roof_items.of_house(gable_house(), None, True, LOOK)
    assert len(found.gutters) == 2 and len(found.pipes) == 4
    for g in found.gutters:
        assert math.dist(g.a, g.b) == pytest.approx(10.6)
        assert g.z == pytest.approx(3.25 - PITCH35 * 0.5)  # низ кровли у края свеса
    assert sorted(round(g.a[1] + g.b[1], 3) for g in found.gutters) == pytest.approx(
        [-1.125, 13.125])  # край свеса 0,5 м + полжелоба от стены
    for p in found.pipes:
        assert min(abs(p.center[1] + 0.045), abs(p.center[1] - 6.045)) == pytest.approx(0)
        assert min(p.center[0], 10 - p.center[0]) == pytest.approx(LOOK.pipe_inset_m)
        assert p.diameter == 0.09 and p.z_top < found.gutters[0].z


def test_hip_roof_gutters_on_all_sides():
    found = roof_items.of_house(hip_house(), None, True, LOOK)
    assert (len(found.gutters), len(found.pipes)) == (4, 8)


def test_house_without_gutters_flag_has_none():
    found = roof_items.of_house(gable_house(), None, False, LOOK)
    assert (found.chimney, found.gutters, found.pipes) == (None, [], [])


def test_parted_house_gutters_stay_off_neighbours(cfg, simple_svg):
    """Г-дом: желоба не заходят в стены и под кровлю другой части и не ложатся друг на друга."""
    plan = preprocess(simple_svg(*L_SHAPE), Mode.WITH_OPENINGS, cfg.plan)
    spec = stub.spec_model("", cfg.models.spec)
    spec = spec.model_copy(update={"roof": cfg.models.spec.roof_shape.roof(RoofKind.GABLE, "roof"),
                                   "gutters": True})
    sheet = pipeline.walls(spec, plan)
    house = roof.roofs(sheet)
    assert len(house.parts) > 1
    found = roof_items.roof_items(sheet, LOOK)
    assert found.gutters and found.pipes
    walls = shapely.union_all([shapely.Polygon(p.corners).buffer(-0.01) for p in house.parts])
    lines = [shapely.LineString([g.a, g.b]) for g in found.gutters]
    assert not any(line.intersects(walls) for line in lines)
    for i, one in enumerate(lines):
        for other in lines[i + 1:]:
            assert one.intersection(other).length < 0.01


# ——— лист, 3D, IFC ———

def test_sheet_draws_chimney_gutters_pipes(house):
    """На виде карнизной стены — труба над кровлей, желоб полосой и две трубы у краёв."""
    spec = house.spec.model_copy(update={"chimney": 0.25, "gutters": True})
    sheet = house.model_copy(update={"spec": spec.model_copy(update={
        "roof": SPEC.roof_shape.roof(RoofKind.GABLE, "roof")})})
    svg = sheet_svg(sheet, CFG)
    assert svg.count("roof-item chimney") == 4 and "roof-item gutter" in svg
    assert svg.count("roof-item pipe") >= 4
    assert LOOK.chimney_fill in svg
    plain = sheet.model_copy(update={"spec": sheet.spec.model_copy(
        update={"chimney": None, "gutters": False})})
    assert "roof-item" not in sheet_svg(plain, CFG)


def test_view_shows_chimney_above_roof_only_on_wall_gutters():
    """Желоб на виде — только у стены, к которой он идёт вдоль; с торца — квадратом."""
    found = roof_items.of_house(gable_house(), 0.25, True, LOOK)
    corners = gable_house().corners
    kinds = [[k for k, _ in roof_items.view(found, corners, i)] for i in range(4)]
    assert all(ItemKind.CHIMNEY in row for row in kinds)
    assert kinds[0].count(ItemKind.GUTTER) == 1 and kinds[2].count(ItemKind.GUTTER) == 1
    assert kinds[1].count(ItemKind.GUTTER) == 2  # торцом: оба желоба, передние концы


def test_3d_data_and_ifc_have_objects(house):
    spec = house.spec.model_copy(update={
        "chimney": 0.25, "gutters": True, "roof": SPEC.roof_shape.roof(RoofKind.GABLE, "roof")})
    sheet = house.model_copy(update={"spec": spec})
    items = house_3d(sheet, CFG)["items"]
    assert items["chimney"]["z1"] > items["chimney"]["z0"]
    assert len(items["gutters"]) == 2 and len(items["pipes"]) == 4
    text = house_ifc(sheet, CFG)
    got = counts(text)
    assert got["IFCCHIMNEY"] == 1
    assert text.count(",.GUTTER.)") == 2
    assert got["IFCPIPESEGMENT"] >= 2 + 4  # желоба и трубы, плюс отводы
    bare = house_ifc(house.model_copy(update={"spec": spec.model_copy(update={
        "chimney": None, "gutters": False})}), CFG)
    assert "IFCCHIMNEY" not in counts(bare) and "IFCPIPESEGMENT" not in counts(bare)


# ——— шаг 1 на стабе ———

def spec_of(text: str):
    return stub.spec_model(text, SPEC)


def test_stub_fireplace_gives_chimney_and_gutters():
    spec = spec_of("деревянный дом с камином и двускатной крышей")
    assert spec.chimney == SPEC.chimney_at and spec.gutters is True


def test_stub_no_gutters_no_chimney():
    spec = spec_of("кирпичный дом без водостока")
    assert spec.gutters is False and spec.chimney is None
    assert spec_of("A brick house, no gutters").gutters is False


def test_stub_chimney_words_and_downpipe_is_not_chimney():
    assert spec_of("A house with a chimney").chimney is not None
    assert spec_of("дом с печью").chimney is not None
    assert spec_of("дом с водосточной трубой").chimney is None
    assert spec_of("дом без камина").chimney is None
    assert spec_of("кирпичный дом").chimney is None  # слов нет — трубы нет, водосток по умолчанию
    assert spec_of("кирпичный дом").gutters is SPEC.gutters_default


def test_stub_flat_roof_has_neither():
    spec = spec_of("дом с камином и плоской крышей")
    assert spec.roof.kind is RoofKind.FLAT and spec.chimney is None and spec.gutters is False


def test_old_json_without_fields_is_valid(raw_house):
    raw_house["spec"].pop("chimney", None)
    raw_house["spec"].pop("gutters", None)
    from genfacade.schema import FacadeSheet
    sheet = FacadeSheet.model_validate(raw_house)
    assert sheet.spec.chimney is None and sheet.spec.gutters is False


# ——— словарь модели ———

def test_model_vocabulary_unchanged_and_condition_ignores_items(house):
    """Модель шага 4 трубу и водосток не видит: словарь тот же, условие не зависит от полей."""
    assert vocab.fingerprint(CFG) == vocab.FROZEN
    with_items = house.model_copy(update={"spec": house.spec.model_copy(
        update={"chimney": 0.25, "gutters": True})})
    assert tokens.condition(with_items, Mode.WITH_OPENINGS, CFG) == tokens.condition(
        house, Mode.WITH_OPENINGS, CFG)


# ——— разметка ———

def chimney_house(x_ft: float, side: int = 1):
    raw = finished().model_dump(mode="json")
    raw["chimney"] = {"side": side, "x": 100.0 + x_ft * PT}
    raw["gutters"] = True
    return manual.house(Markup.model_validate(raw), CFG.data.manual)[0].sheet.spec


def test_markup_chimney_becomes_ridge_fraction():
    """Труба в 5' и в 15' на виде стены 20' — доли 0,25 и 0,75 (в каком порядке — от начала
    конька); водосток из разметки."""
    near, far = chimney_house(5).chimney, chimney_house(15).chimney
    assert sorted([near, far]) == pytest.approx([0.25, 0.75])
    assert chimney_house(5).gutters is True and near != far


def test_markup_chimney_beyond_wall_clamps_and_far_is_error():
    """Центр за краем стены — труба у торца конька; дальше края кровли на chimney_beyond_m —
    ошибка; неверная сторона — ошибка."""
    assert chimney_house(-0.5).chimney in (0.0, 1.0)
    assert chimney_house(20.5).chimney in (0.0, 1.0)
    with pytest.raises(BadMarkup):
        chimney_house(-5)
    with pytest.raises(BadMarkup):
        chimney_house(5, side=9)
    raw = finished().model_dump(mode="json")
    raw["chimney"], raw["roof_kind"], raw["pitch_deg"] = {"side": 1, "x": 150.0}, "flat", 0.0
    with pytest.raises(BadMarkup):
        manual.house(Markup.model_validate(raw), CFG.data.manual)


def test_eave_view_draws_pipes_and_gutter_over_wall_and_roof(house):
    """На виде карнизной стены трубы — полосы 0,09 м в 0,15 м от углов в пределах стены, желоб —
    полоса 0,125 м; в документе они идут после стены и кровли (рисуются поверх)."""
    import re
    spec = house.spec.model_copy(update={
        "gutters": True, "roof": SPEC.roof_shape.roof(RoofKind.GABLE, "roof")})
    svg = sheet_svg(house.model_copy(update={"spec": spec}), CFG)
    group = svg.split('class="facade"')[1].split("</g>")[0]  # первый вид — карнизная стена
    assert group.index('class="roof"') < group.index("roof-item pipe")
    assert group.index('class="roof"') < group.index("roof-item gutter")
    xs = []
    for m in re.finditer(r'class="roof-item pipe" points="([^"]+)"', group):
        pts = [tuple(map(float, p.split(","))) for p in m[1].split()]
        xs.append((min(x for x, _ in pts), max(x for x, _ in pts)))
    assert len(xs) == 2
    assert all(b - a == pytest.approx(0.09) for a, b in xs)
    length = house.facades[0].side.length_m
    assert sorted(round(a + 0.045, 3) for a, _ in xs) == pytest.approx([0.15, length - 0.15])
    gutter = re.search(r'class="roof-item gutter" points="([^"]+)"', group)[1]
    ys = [float(p.split(",")[1]) for p in gutter.split()]
    assert max(ys) - min(ys) == pytest.approx(0.125)
