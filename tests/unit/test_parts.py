"""Дом из частей разной высоты (gf#322, `facade: Части дома`): крылья контура на шаге 2, участки и
ступенчатый силуэт на шаге 3, раскладка участков моделью на шаге 4, углы на стыках частей."""

import math

import pytest
import shapely
from simple_house import L_SHAPE, SIMPLE, U_SHAPE

from genfacade import config, parts, pipeline, roof
from genfacade.models import stub
from genfacade.plan.preprocess import preprocess
from genfacade.plan.wings import wings
from genfacade.render.house3d import house_3d
from genfacade.render.svg import sheet_svg
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    FixedField,
    MaterialZone,
    Mode,
    Opening,
    OpeningKind,
    Rect,
    Rule,
    SideFacade,
    ZoneRole,
)
from genfacade.validate import errors, validate

CFG = config.load()
TWO_PARTS = "A two-storey house with a single-storey wing."
GOLDEN = SIMPLE.parents[1] / "golden" / "simple_house_sheet.svg"  # лист простого дома до gf#322


# Г из simple_house.svg с вырезом 2,05 × 2 м (стенка 880–895 px): стык частей правее входа
# (в L_SHAPE он на входе).
L_PARTS = (
    (L_SHAPE[0][0],
     '<rect x="800" y="100" width="95" height="15" fill="#000000" />'
     '<rect x="880" y="100" width="15" height="215" fill="#000000" />'
     '<rect x="880" y="300" width="220" height="15" fill="#000000" />'),
    *L_SHAPE[1:],
)


def l_plan(replacements=L_PARTS):
    text = SIMPLE.read_text()
    for old, new in replacements:
        text = text.replace(old, new)
    return preprocess(text, Mode.WITH_OPENINGS, CFG.plan)


def bare(text: str = TWO_PARTS, replacements=L_PARTS) -> FacadeSheet:
    return pipeline.walls(stub.spec_model(text, CFG.models.spec), l_plan(replacements),
                          CFG.plan.parts)


_CLASS = {OpeningKind.WINDOW: ElementClass.WINDOW, OpeningKind.DOOR: ElementClass.DOOR,
          OpeningKind.ENTRANCE: ElementClass.DOOR}


def plain_wall(wall: SideFacade, ctx: stub.LayoutContext) -> SideFacade:
    """Ответ «модели» без обучения: окно посередине, цоколь, основная отделка, карниз — для теста
    сборки участков в дом. Параметры стены — её части: ctx.spec."""
    spec, length = ctx.spec, wall.side.length_m
    materials = {m.id: m.id for m in spec.materials}
    planned = [Element(id=f"o{k}", cls=_CLASS[o.kind], x_m=o.x_m, w_m=o.width_m, floor=1,
                       y_m=spec.plinth_m + (0 if o.kind is not OpeningKind.WINDOW else 0.9),
                       h_m=2.0 if o.kind is not OpeningKind.WINDOW else 1.2,
                       fixed=[FixedField.X, FixedField.W])
               for k, o in enumerate(wall.side.openings)]
    window = Element(id="w1", cls=ElementClass.WINDOW, x_m=length / 2 - 0.6,
                     y_m=spec.plinth_m + 0.9, w_m=1.2, h_m=1.2, floor=1)
    cornice = Element(id="c1", cls=ElementClass.CORNICE, x_m=0.0, y_m=spec.eaves_m - 0.2,
                      w_m=length, h_m=0.2, floor=spec.floors)
    zones = [MaterialZone.rect(ZoneRole.PLINTH, materials["plinth"], (0, 0, length, spec.plinth_m)),
             MaterialZone.rect(ZoneRole.MAIN, materials["main"],
                               (0, spec.plinth_m, length, spec.eaves_m))]
    return wall.model_copy(update={"elements": [*(planned or [window]), cornice],
                                    "zones": zones})


@pytest.fixture
def plain_model(monkeypatch):
    monkeypatch.setattr(pipeline, "trained_model", lambda settings: None)
    monkeypatch.setattr(stub, "layout_all", lambda sheet, ctx: sheet.model_copy(update={
        "facades": [plain_wall(f, ctx) for f in sheet.facades]}))


def laid_out(cfg=CFG) -> pipeline.Checked:
    req = pipeline.PlanRun(plan="l", text=TWO_PARTS)
    return pipeline.layout(bare(), req, cfg)


def south_wall(sheet: FacadeSheet | None = None):
    """Южная стена собранного дома и её участок нижней части: лист, стена, участок."""
    sheet = sheet or laid_out().sheet
    south = sheet.facades[0]
    return sheet, south, next(r for r in south.runs if r.floors == 1)


def heights_at(f: SideFacade, x: float) -> tuple[float, float]:
    """Низ и верх силуэта стены на вертикали x (ступень даёт две высоты — берём верх правее)."""
    ys = [y for px, y in f.silhouette if abs(px - x) <= EPS]
    return min(ys), max(ys)


# ——— шаг 2: крылья контура ———


def test_rectangle_is_one_part():
    assert l_plan(()).wings == []


def test_l_shape_splits_into_two_wings_main_whole():
    """Г режется двумя способами; основной объём остаётся целым — самое большое крыло больше."""
    plan = l_plan()
    areas = sorted((w.x1_m - w.x0_m) * (w.y1_m - w.y0_m) for w in plan.wings)
    assert len(plan.wings) == 2 and areas[1] > areas[0]
    assert sum(areas) == pytest.approx(10 * 5 - 2.05 * 2)  # контур: крылья его покрывают


def test_u_shape_splits_into_three_wings():
    assert len(l_plan(U_SHAPE).wings) == 3


# Контур дома ffh-mae из разметки: углы с хвостами float (2,7432000000000007; 1,8491199999999992).
NOISY = [(0.0, 6.726), (8.534400000000003, 6.726), (8.534400000000003, 4.321386666666667),
         (10.306, 4.321386666666667), (10.306, 1.84912), (5.791200000000001, 1.84912),
         (5.791200000000001, 0.0), (2.7432000000000007, 0.0),
         (2.7432000000000007, 1.8491199999999992), (0.0, 1.8491199999999992)]


def test_wings_of_contour_with_float_noise():
    """Хвосты float в углах не мешают разрезу: три крыла, они покрывают контур."""
    found = wings(NOISY)
    assert len(found) == 3
    assert sum((w.x1_m - w.x0_m) * (w.y1_m - w.y0_m) for w in found) == pytest.approx(
        shapely.Polygon(NOISY).area)


def test_wings_are_deterministic():
    outline = l_plan().outline
    assert wings(outline) == wings(outline)


# ——— шаг 3: участки и силуэт ———


def test_wall_between_parts_has_stepped_silhouette():
    """Южная стена Г: слева двухэтажное крыло, справа одноэтажное — силуэт ступенью, а не
    прямоугольником до карниза главной части."""
    sheet = bare()
    south = sheet.facades[0]
    high, low = sheet.spec.eaves_m, sheet.spec.floor_levels()[1]
    assert [(r.floors, r.eaves_m) for r in south.runs] == [(2, high), (1, low)]
    step = south.runs[0].x1_m
    assert south.silhouette == [(0, 0), (south.side.length_m, 0), (south.side.length_m, low),
                                (step, low), (step, high), (0, high)]


def test_wall_of_one_part_stays_rectangle():
    sheet = bare()
    for f in sheet.facades[1:]:
        assert len(f.silhouette) == 4 and len(f.runs) == 1


def test_same_height_parts_give_no_steps():
    """Крылья одной высоты — прежний дом: участков нет, стена прямоугольная."""
    one = bare("A one-storey house.")
    assert not parts.stepped(one)
    assert all(len(f.silhouette) == 4 for f in one.facades)


def test_rule_lowers_smaller_wing_without_words():
    """Текст молчит — меньшее крыло ниже на этаж (config/plan.toml, [parts])."""
    sheet = bare("A two-storey house.")
    assert sorted({r.floors for f in sheet.facades for r in f.runs}) == [1, 2]


def test_narrow_projection_stays_at_main_height():
    """Выступ уже `wing_min_m` — эркер, а не крыло: на высоте главной части."""
    rule = CFG.plan.parts.model_copy(update={"wing_min_m": 3.5})
    spec = stub.spec_model(TWO_PARTS, CFG.models.spec)
    assert not parts.stepped(pipeline.walls(spec, l_plan(), rule))


def test_house_without_rule_and_words_has_no_steps():
    """Конвейер без правила и без слов (синтетика, разметка) дом не ступенит."""
    spec = stub.spec_model("A two-storey house.", CFG.models.spec)
    assert not parts.stepped(pipeline.walls(spec, l_plan()))


def test_floor_words_do_not_read_the_wing():
    """«Одноэтажное крыло» не делает одноэтажным весь дом."""
    spec = stub.spec_model("A single-storey wing on a two-storey house", CFG.models.spec)
    assert (spec.floors, spec.wing_floors) == (2, 1)


# ——— углы и стыки частей ———


def corner_heights(sheet: FacadeSheet):
    """Для каждого угла i+1: верх левой стены i и правой стены i+1 у угла."""
    fs = sheet.facades
    return [(heights_at(a, 0.0)[1], heights_at(b, b.side.length_m)[1])
            for a, b in zip(fs, fs[1:] + fs[:1], strict=True)]


def test_corners_of_one_part_meet():
    """Угол двух стен одной части: высоты равны по построению; стык частей — нижняя стена у
    верхней, их высоты — этажность своих частей."""
    sheet = bare()
    for (ha, hb), (a, b) in zip(corner_heights(sheet), zip(sheet.facades, sheet.facades[1:]
                                                           + sheet.facades[:1], strict=True),
                                strict=True):
        pa, pb = a.runs[0], b.runs[-1]
        if pa.part == pb.part:
            assert ha == hb == pa.eaves_m
        else:
            assert (ha, hb) == (pa.eaves_m, pb.eaves_m)
    assert not [v for v in validate(sheet, CFG.checks) if v.rule is Rule.CORNER]


def test_wall_end_not_matching_its_part_is_a_corner_error():
    """Край стены поднят над карнизом её части — с соседней стеной той же части не сходится."""
    sheet = bare()
    east = sheet.facades[3]  # стена главной части: поднимаем её правый край — угол с севером
    length = east.side.length_m
    tall = [(x, y + 1.0 if y > 1 and x == length else y) for x, y in east.silhouette]
    broken = sheet.model_copy(update={"facades": [
        f if f is not east else f.model_copy(update={"silhouette": tall}) for f in sheet.facades]})
    assert [v.rule for v in validate(broken, CFG.checks) if v.rule is Rule.CORNER]


# ——— шаг 4–5: участки как стены ———


def test_each_part_gets_its_own_wall_for_the_model(plain_model):
    """Модель видит участок как стену с параметрами своей части; ответы собираются на стену дома."""
    made = laid_out()
    sheet = made.sheet
    south = sheet.facades[0]
    assert {e.id for e in south.elements if e.cls is ElementClass.WINDOW} == {"r0_o0", "r1_w1"}
    low = next(r for r in south.runs if r.floors == 1)
    window = next(e for e in south.elements if e.id == "r1_w1")
    assert window.x_m >= low.x0_m - EPS and window.x_m + window.w_m <= low.x1_m + EPS


def test_cornice_of_part_is_one_on_all_its_sides(plain_model):
    """Карниз части — на одной отметке на всех её сторонах: верх карниза = карниз части."""
    sheet = laid_out().sheet
    tops = {}
    for f in sheet.facades:
        for c in (e for e in f.elements if e.cls is ElementClass.CORNICE):
            middle = c.x_m + c.w_m / 2
            run = next(r for r in f.runs if r.x0_m <= middle <= r.x1_m)
            tops.setdefault(run.part, set()).add(round(c.y_m + c.h_m, 6))
            assert math.isclose(c.y_m + c.h_m, run.eaves_m, abs_tol=EPS)
    assert {p: len(t) for p, t in tops.items()} == {0: 1, 1: 1}
    assert len({max(t) for t in tops.values()}) == 2  # у частей карнизы разные


def test_laid_out_house_has_no_errors_and_steps_on_sheet(plain_model):
    made = laid_out()
    assert not errors(made.violations), made.violations
    svg = sheet_svg(made.sheet, CFG)
    assert svg.startswith("<svg")


def test_window_wider_than_its_part_is_outside(plain_model):
    """Элемент низкой части выше её карниза — вне силуэта стены (проверка по сборке дома)."""
    sheet, south, low = south_wall()
    tall = Element(id="x", cls=ElementClass.WINDOW, x_m=low.x0_m + 0.2, y_m=3.0, w_m=0.8, h_m=1.5,
                   floor=1)
    broken = sheet.model_copy(update={"facades": [
        south.model_copy(update={"elements": [*south.elements, tall]}), *sheet.facades[1:]]})
    assert Rule.OUTSIDE in {v.rule for v in validate(broken, CFG.checks)}


def with_south(sheet: FacadeSheet, **update) -> FacadeSheet:
    south = sheet.facades[0].model_copy(update=update)
    return sheet.model_copy(update={"facades": [south, *sheet.facades[1:]]})


def test_zone_ending_at_part_boundary_is_anchored(plain_model):
    """Акцент, что кончается там, где кончается часть дома, — не обрыв отделки посреди стены."""
    sheet = laid_out().sheet
    south = sheet.facades[0]
    edge = south.runs[0].x1_m
    accent = MaterialZone.rect(ZoneRole.ACCENT, "accent", (0.0, 0.6, edge, 1.4))
    far = [e for e in south.elements if e.cls is ElementClass.WINDOW]  # без двери у границы частей
    found = validate(with_south(sheet, zones=[*south.zones, accent], elements=far), CFG.checks)
    assert not [v for v in found if v.rule is Rule.FINISH]


def straddling(width: float, x: float = 7.0) -> FacadeSheet:
    """Дом, у которого на южной стене проём плана лежит через границу частей (x = 7,95 м)."""
    sheet = bare()
    south = sheet.facades[0]
    opening = Opening(kind=OpeningKind.WINDOW, x_m=x, width_m=width)
    side = south.side.model_copy(update={"openings": [opening], "has_entrance": False})
    return sheet.model_copy(update={"facades": [south.model_copy(update={"side": side}),
                                                *sheet.facades[1:]]})


def test_opening_on_part_boundary_goes_to_part_with_bigger_share(plain_model):
    """Проём 1,5 м с x = 7: 0,95 м у главной части, 0,55 м — у нижней; он отдан главной, обрезан
    по её краю, и конвейер не бракует план (`facade: Части дома`)."""
    sheet = straddling(1.5)
    subs = parts.sub_sheets(sheet)
    (high, _), (low, _) = (subs[n] for n in sorted(subs, reverse=True))
    assert [(o.x_m, o.width_m) for o in high.facades[0].side.openings] == [
        (pytest.approx(7.0), pytest.approx(0.95))]
    assert not low.facades[0].side.openings
    made = pipeline.layout(sheet, pipeline.PlanRun(plan="l", text=TWO_PARTS), CFG)
    assert Rule.PLAN_OPENING not in {v.rule for v in made.violations}
    window = next(e for e in made.sheet.facades[0].elements if e.x_m == pytest.approx(7.0))
    assert window.w_m == pytest.approx(0.95)


def test_opening_with_bigger_share_in_lower_part_goes_there(plain_model):
    """Проём 1,5 м с x = 7,5: 0,45 м у главной, 1,05 м — у нижней: отдан нижней."""
    sheet = straddling(1.5, 7.5)
    subs = parts.sub_sheets(sheet)
    low = subs[min(subs)][0]
    assert [(o.x_m, o.width_m) for o in low.facades[0].side.openings] == [
        (pytest.approx(0.0), pytest.approx(1.05))]


def test_window_heads_are_compared_within_a_part(plain_model):
    """Верх окон первого этажа у главной и нижней частей — разный (каждая часть держит свою
    линию), предупреждение «верх на разной высоте» — только внутри части."""
    sheet, south, low = south_wall()
    high = [e for e in south.elements if e.cls is ElementClass.WINDOW and e.x_m < low.x0_m]
    other = [e for e in south.elements if e.cls is ElementClass.WINDOW and e.x_m >= low.x0_m]
    raised = [e.model_copy(update={"y_m": e.y_m + 0.3}) for e in other]
    mixed = with_south(sheet, elements=[e for e in south.elements if e not in other] + raised)
    assert Rule.FLOOR_ALIGN not in {v.rule for v in validate(mixed, CFG.checks)}
    same = [high[0].model_copy(update={"id": "z", "x_m": high[0].x_m + 1.3, "y_m": 2.4})]
    again = with_south(sheet, elements=[*south.elements, *same])
    assert Rule.FLOOR_ALIGN in {v.rule for v in validate(again, CFG.checks)}


# ——— 3D ———


def in_3d(made: pipeline.Checked):
    """Дом объёмом: собранный дом, его данные для просмотра, карниз высокой и нижней частей."""
    high, low = (r.eaves_m for r in made.sheet.facades[0].runs)
    return made, house_3d(made.sheet, CFG), high, low


def test_house_3d_walls_and_roof_follow_parts(plain_model):
    """В 3D стена — до верха своей высокой части, над нижней частью текстура прозрачна, плита
    кровли — над каждой частью на её карнизе."""
    made, data, high, low = in_3d(laid_out())
    assert [w["height_m"] for w in data["walls"]] == [high, high, high, high, low, low]
    assert 'class="background"' not in data["walls"][0]["svg"]
    assert 'class="background"' in data["walls"][1]["svg"]
    assert not data["roof"].get("slabs")  # скатная крыша (по умолчанию двускатная) — скаты частей
    tops = sorted({round(z, 3) for face in data["roof"]["faces"] for _, _, z in face})
    assert low - 0.5 < min(tops) <= low and max(tops) > high  # свес опускает кромку ниже карниза


def test_flat_roof_of_parts_is_slab_per_part(plain_model):
    """Плоская крыша дома из частей — плита над каждой частью на её карнизе, как до скатов."""
    flat = TWO_PARTS + " Flat roof."
    made = pipeline.layout(bare(flat), pipeline.PlanRun(plan="l", text=flat), CFG)
    _, data, high, low = in_3d(made)
    assert sorted(s["height_m"] for s in data["roof"]["slabs"]) == [low, high]
    assert "material" in data["roof"] and "wall_material" in data["roof"]  # рисунок кровли (gf#353)


def test_gable_roof_of_parts_keeps_materials(plain_model):
    """Скаты частей (gf#322) выкладываются рисунком материала, как скаты обычной крыши (gf#353)."""
    made = pipeline.layout(bare(GABLE), pipeline.PlanRun(plan="l", text=GABLE), CFG)
    _, data, _, _ = in_3d(made)
    roof_part = data["roof"]
    assert roof_part["faces"] and {"material", "wall_material"} <= roof_part.keys()
    assert roof_part["material"] in data["swatches"] or roof_part["material"] is None


# ——— скаты над частями (gf#322) ———


GABLE = TWO_PARTS + " Gable roof."


def gable_house() -> tuple[FacadeSheet, roof.HouseRoof]:
    sheet = bare(GABLE)
    return sheet, roof.roofs(sheet)


def test_each_part_has_its_own_slopes_at_its_own_eaves():
    """Г-дом 2 и 1 этаж: у каждой части скаты от её карниза; конёк нижней — ниже карниза верхней."""
    sheet, house = gable_house()
    main, wing = house.parts
    assert (main.eaves, wing.eaves) == (pytest.approx(6.0), pytest.approx(3.25))
    assert main.slopes and wing.slopes
    ridge = {k: max(z for _, face in roof.faces(line) for _, _, z in face)
             for k, line in enumerate(house.parts)}
    assert ridge[0] > main.eaves and ridge[1] > wing.eaves
    assert ridge[1] < main.eaves  # конёк нижней части ниже карниза верхней


def test_roof_of_lower_part_ends_at_wall_of_higher():
    """Кровля нижней части не заходит за стену верхней: ни одна её точка не над крылом верхней."""
    _, house = gable_house()
    main = shapely.Polygon(house.parts[0].corners)
    wing_faces = roof.faces(house.parts[1], roof._area(house, 1))
    assert wing_faces
    for _, face in wing_faces:
        assert shapely.Polygon([(x, y) for x, y, _ in face]).intersection(main).area < EPS


def test_junction_is_on_wall_of_higher_part():
    """Примыкание — на стене верхней части: линия кровли нижней на её плоскости, а выше — стена."""
    sheet, house = gable_house()
    (joint,) = roof.joints(house)
    wall_x = house.parts[0].corners[1][0]  # восточная грань главного крыла
    assert {round(x, 6) for x, _, _ in joint.seam} == {round(wall_x, 6)}
    assert joint.normal == pytest.approx((1.0, 0.0))
    assert min(z for w in joint.walls for _, _, z in w) >= house.parts[1].eaves - EPS
    assert max(z for w in joint.walls for _, _, z in w) > house.parts[0].eaves  # щипец главной
    east = next(k for k, f in enumerate(sheet.facades) if f.side.length_m == pytest.approx(3.0))
    svg = sheet_svg(sheet, CFG)
    assert svg.count('class="outline joint"') == 1
    group = svg.split(f'data-side="{east}"')[1].split("</g>")[0]
    assert 'class="outline joint"' in group and 'class="above-eaves"' in group


def test_stepped_house_with_pitched_roof_has_no_roof_flat_warning():
    sheet, _ = gable_house()
    assert Rule.ROOF_FLAT not in {v.rule for v in validate(sheet, CFG.checks)}
    flat = bare(TWO_PARTS + " Flat roof.")
    assert Rule.ROOF_FLAT not in {v.rule for v in validate(flat, CFG.checks)}  # плоская — нечего


def test_hip_roof_of_each_part_rises_to_its_own_ridge():
    sheet = bare(TWO_PARTS + " Hip roof.")
    house = roof.roofs(sheet)
    # у нижней части скат не идёт от стены верхней
    assert len(house.parts[0].slopes) == 4 and len(house.parts[1].slopes) == 3
    assert max(z for face in roof.house_faces(house) for _, _, z in face) > house.parts[0].eaves


def test_jog_narrower_than_overhang_has_no_roof_of_its_own():
    """Уступ контура уже свеса (у разметки — шум в сантиметры) крышу не несёт: он под соседними."""
    sheet, house = gable_house()
    jog = Rect(x0_m=0.0, y0_m=0.0, x1_m=5.0, y1_m=house.parts[0].overhang - 0.1)
    line = roof._part_line(sheet, 0, jog, 3.0, 0.7, [])
    assert not line.slopes and line.height((1.0, 0.1)) == pytest.approx(3.0)
    assert roof._part_line(sheet, 0, Rect(x0_m=0.0, y0_m=0.0, x1_m=5.0, y1_m=2.0), 3.0, 0.7,
                           []).slopes


def test_roof_view_hides_part_behind_nearer_wall():
    """С севера крыша крыла за главным не видна ниже карниза главного: на листе нет её скатов."""
    sheet, house = gable_house()
    north = next(k for k, f in enumerate(sheet.facades) if house.spans[k] == [roof.Span(
        0.0, f.side.length_m, 0)] and math.dist(f.side.orientation, (0.0, 1.0)) < EPS)
    shown = roof.house_view(house, north, 0.1)
    assert all(y > house.parts[1].eaves for poly in shown for _, y in poly)


# ——— прямоугольный дом — прежний ———


def test_rectangular_house_sheet_is_byte_for_byte_as_before(cfg, tmp_path):
    """Прямоугольный дом — одна часть, лист тот же, что до gf#322 (tests/fixtures)."""
    req = pipeline.PlanRun(plan=str(SIMPLE), text="A simple one-storey house")
    out = pipeline.generate(req, SIMPLE.read_text(), tmp_path / "run", cfg)
    assert (out / pipeline.SHEET).read_text() == GOLDEN.read_text()
