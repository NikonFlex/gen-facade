"""Ручная разметка реальных коттеджей → примеры теста (`data: Реальные коттеджи — тест`,
`data: Стена до карниза в данных`): прямоугольники в pt листа → элементы в метрах от земли;
контур — ортогональный, с внутренними углами (gf#199)."""

import json
import math
from pathlib import Path

import pytest

from genfacade import config, roof
from genfacade.datasets import manual, markup_toml, store
from genfacade.datasets.manual import M_PER_UNIT, Markup, Unit
from genfacade.metrics import measures
from genfacade.schema import (
    ElementClass,
    Facing,
    Mode,
    OpeningKind,
    RoofKind,
    Rule,
    Source,
    Split,
    Trim,
)
from genfacade.train import tokens
from genfacade.train.tokens import Mark
from genfacade.validate import errors, validate

CFG = config.load()
M_PER_FT = M_PER_UNIT[Unit.FT]
PT = 18.0       # pt на фут: лист 1/4" = 1'-0"
FLOOR = 500.0   # отметка чистого пола на листе, pt
PLINTH_FT, EAVE_FT = 1.0, 8.0   # пол над землёй и карниз над полом, футы
PITCH, OVERHANG = 32.0, 0.5     # крыша дома из разметки: 7.5/12 и свес


def ft(v: float) -> float:
    return v * M_PER_FT


def pt_y(above_floor_ft: float) -> float:
    """Отметка над чистым полом → y листа: y листа растёт вниз."""
    return FLOOR - above_floor_ft * PT


def side(view: str, length_ft: float, *elements: dict) -> dict:
    return {"view": view, "page": 1, "wall": [100.0, 100.0 + length_ft * PT], "floor": FLOOR,
            "elements": list(elements)}


def box(x_ft: float, bottom_ft: float, w_ft: float, h_ft: float) -> list[float]:
    """Прямоугольник листа по отступу от левого края стены и отметкам над полом."""
    return [100.0 + x_ft * PT, pt_y(bottom_ft + h_ft), 100.0 + (x_ft + w_ft) * PT, pt_y(bottom_ft)]


def markup(**changes) -> Markup:
    """Дом 12' × 20': дверь на стороне входа, окно со ставней справа, навес над дверью выше
    карниза и окно, чуть заходящее за карниз."""
    raw = {"id": "ffh-test", "pdf": "test.pdf", "roof": "двускатная",
           "roof_kind": "gable", "pitch_deg": PITCH, "overhang_m": OVERHANG, "unit": "ft",
           "pt_per_unit": PT, "material": "siding", "plinth": PLINTH_FT, "floor_heights": [EAVE_FT],
           "cut": ["front: фронтон"],
           "sides": [side("FRONT", 12,
                          {"cls": "door", "box": box(5, 0, 2, 6.75)},
                          {"cls": "canopy", "box": box(4.5, 7.5, 3, 1.5)}),
                     side("LEFT", 20,
                          {"cls": "window", "box": box(9, 3, 2, 4.5),
                           "variant": {"cols": 2, "rows": 2}},
                          {"cls": "blind", "box": box(11, 3, 1, 4.5), "parent": 0}),
                     side("REAR", 12),
                     side("RIGHT", 20, {"cls": "window", "box": box(3, 3, 2, 5.5)})]}
    return Markup.model_validate(raw | changes)


def test_markup_becomes_sample_in_metres():
    sample, dropped = manual.house(markup(), CFG.data.manual)
    front, left, _, right = sample.sheet.facades
    door = front.elements[0]
    assert (sample.source, sample.split) == (Source.MANUAL, Split.TEST)
    assert [f.side.length_m for f in sample.sheet.facades] == pytest.approx(
        [ft(12), ft(20), ft(12), ft(20)])
    assert (door.x_m, door.y_m, door.w_m, door.h_m) == pytest.approx(
        (ft(5), ft(PLINTH_FT), ft(2), ft(6.75)))
    assert sample.sheet.spec.eaves_m == pytest.approx(ft(PLINTH_FT + EAVE_FT))
    assert left.elements[1].parent == left.elements[0].id
    assert left.elements[0].variant.cols == 2
    # Навес — на 0,5' ниже карниза из 1,5': внутри меньше половины, его нет.
    assert [e.cls for e in front.elements] == [ElementClass.DOOR]
    assert dropped == 1
    # Окно до 8,5' над полом обрезано по карнизу на 8'.
    assert right.elements[0].y_m + right.elements[0].h_m == pytest.approx(ft(PLINTH_FT + EAVE_FT))
    assert front.side.has_entrance and front.side.openings[0].kind is OpeningKind.ENTRANCE
    assert errors(validate(sample.sheet, CFG.checks)) == []


def test_roof_from_markup_and_no_cornice_under_gable():
    """Крыша дома — из полей разметки (gf#336, `data: Разметка — запись чертежа целиком`): вид,
    уклон и свес в параметрах дома; карниз с листа остаётся на стенах под краем ската, а на
    щипцовых (короткие стены двускатной) снят (`facade: Карниз под скатом`)."""
    raw = finished().model_dump(mode="json")
    raw["sides"][0]["elements"].append({"cls": "cornice", "box": box(0, EAVE_FT - 0.75, 12, 0.75)})
    sample, dropped = manual.house(Markup.model_validate(raw), CFG.data.manual)
    roof = sample.sheet.spec.roof
    assert (roof.kind, roof.pitch_deg, roof.overhang_m) == (RoofKind.GABLE, PITCH, OVERHANG)
    has = [any(e.cls is ElementClass.CORNICE for e in f.elements) for f in sample.sheet.facades]
    assert has == [False, True, False, False]  # гребень вдоль 20': щипцы на стенах по 12'
    assert dropped == 2  # навес за карнизом и полоса на щипцовой стене
    assert errors(validate(sample.sheet, CFG.checks)) == []


def test_flat_markup_keeps_cornice_on_every_wall():
    """Плоская крыша: край крыши над всеми стенами, карниз с листа не снимается."""
    raw = finished().model_dump(mode="json")
    raw["sides"][0]["elements"].append({"cls": "cornice", "box": box(0, EAVE_FT - 0.75, 12, 0.75)})
    flat = Markup.model_validate(raw | {"roof_kind": "flat", "pitch_deg": 0.0, "overhang_m": 0.0})
    sample, _ = manual.house(flat, CFG.data.manual)
    assert sample.sheet.spec.roof.kind is RoofKind.FLAT
    assert [any(e.cls is ElementClass.CORNICE for e in f.elements)
            for f in sample.sheet.facades] == [True, True, False, False]


def test_trims_link_to_their_opening():
    """Выводимый элемент без родителя в разметке (gf#212) — к проёму по месту: подоконник к окну
    над ним, ставня к окну сбоку, козырёк к двери под ним; вид у дома — по умолчанию у тех, что
    есть, у остальных — нет. В токенах они — признаки проёма."""
    sides = [side("FRONT", 12, {"cls": "door", "box": box(5, 0, 2, 6.75)},
                  {"cls": "canopy", "box": box(4.5, 7.0, 3, 0.5)}),
             side("LEFT", 20, {"cls": "window", "box": box(9, 3, 2, 4.5)},
                  {"cls": "blind", "box": box(8, 3, 1, 4.5)},
                  {"cls": "sill", "box": box(8.8, 2.8, 2.4, 0.2)},
                  {"cls": "sill", "box": box(15, 1, 2, 0.2)}),   # не под окном — без родителя
             side("REAR", 12), side("RIGHT", 20)]
    sample, _ = manual.house(markup(sides=sides), CFG.data.manual)
    front, left, *_ = sample.sheet.facades
    door, canopy = front.elements
    window, blind, sill, stray = left.elements
    assert (canopy.parent, blind.parent, sill.parent, stray.parent) == (
        door.id, window.id, window.id, None)
    trim = sample.sheet.spec.trim
    assert (trim.sill, trim.shutters, trim.canopy) == (
        CFG.data.manual.trim.sill, CFG.data.manual.trim.shutters, CFG.data.manual.trim.canopy)
    assert not trim.has(Trim.CASING)
    answer = tokens.answer(sample.sheet, Mode.WITH_OPENINGS, CFG)
    assert {tokens.tok(t) for t in (Trim.SILL, Trim.SHUTTERS, Trim.CANOPY)} <= set(answer)


def test_contour_must_close():
    sides = markup().model_dump()["sides"]
    sides[2] = side("REAR", 14)  # тыл на 2' длиннее фасада: обход не возвращается в начало
    with pytest.raises(manual.BadContour, match="не замкнулся"):
        manual.house(markup(sides=sides), CFG.data.manual)


def l_sides() -> list[dict]:
    """Стороны Г-дома: фасад 12', бок 20', тыл 6', внутренний угол, бок крыла 8', тыл крыла 6',
    другой бок 28'."""
    return [side("FRONT", 12, {"cls": "door", "box": box(5, 0, 2, 6.75)}),
            side("LEFT", 20), side("REAR WING", 6) | {"inner_corner": True},
            side("WING SIDE", 8), side("REAR", 6), side("RIGHT", 28)]


def test_l_shaped_house(tmp_path):
    """Г-образный дом (gf#199): шесть сторон; план замкнут, лист проходит валидатор."""
    sample, _ = manual.house(markup(sides=l_sides()), CFG.data.manual)
    lengths = [f.side.length_m for f in sample.sheet.facades]
    assert lengths == pytest.approx([ft(v) for v in (12, 20, 6, 8, 6, 28)])
    assert len(sample.plan.outline) == 6 and len(sample.plan.walls) == 6
    assert errors(validate(sample.sheet, CFG.checks)) == []


LOW_FT = 5.0  # карниз нижнего крыла над чистым полом: этажность та же, отметка ниже


def stepped_l(lines: dict[int, list[tuple[float, float, float]]]) -> Markup:
    """Г-дом из test_l_shaped_house с участками карниза: сторона → [(x0, x1 в футах от левого края,
    карниз над полом)], все в один этаж. Крылья разреза контура: 12' × 20' и 6' × 8' (стороны 3, 4
    и последние 8' стороны 5)."""
    sides = l_sides()
    for k, marks in lines.items():
        sides[k]["eaves"] = [{"x": [100.0 + a * PT, 100.0 + b * PT], "y": pt_y(h), "floors": 1}
                             for a, b, h in marks]
    return markup(sides=sides)


def test_parts_of_different_eaves_become_steps():
    """Нижнее крыло Г-дома, в одну этажность с главным, но с карнизом ниже (gf#322): участки
    сторон, ступень силуэта и крылья в плане; стены без отметок — карниз дома."""
    lines = {3: [(0, 8, LOW_FT)], 4: [(0, 6, LOW_FT)], 5: [(0, 20, EAVE_FT), (20, 28, LOW_FT)]}
    sample, _ = manual.house(stepped_l(lines), CFG.data.manual)
    assert len(sample.plan.wings) == 2
    run = {f.side.index: f.runs for f in sample.sheet.facades}
    assert [r.eaves_m for r in run[5]] == pytest.approx([ft(PLINTH_FT + EAVE_FT),
                                                         ft(PLINTH_FT + LOW_FT)])
    assert [r.part for r in run[5]] == [0, 1]
    assert [(r.part, r.eaves_m) for r in run[0]] == [(0, pytest.approx(ft(PLINTH_FT + EAVE_FT)))]
    assert {r.floors for rs in run.values() for r in rs} == {1}
    assert run[3][0].eaves_m == pytest.approx(ft(PLINTH_FT + LOW_FT))
    assert len(sample.sheet.facades[5].silhouette) == 6  # ступень
    assert errors(validate(sample.sheet, CFG.checks)) == []
    assert Rule.ROOF_FLAT not in {v.rule for v in validate(sample.sheet, CFG.checks)}


def test_roof_direction_and_part_roofs_from_markup():
    """Направление ската и крыша части из разметки (gf#431): скат дома — к стороне 1, у крыла
    Г-дома, видного на стороне 3, — односкатная 3:12 низом к стороне 4 (торец крыла)."""
    sample, _ = manual.house(markup(roof_down=1), CFG.data.manual)
    assert sample.sheet.spec.roof.down_to is Facing.of(sample.sheet.facades[1].side.orientation)
    lines = {3: [(0, 8, LOW_FT)], 4: [(0, 6, LOW_FT)], 5: [(0, 20, EAVE_FT), (20, 28, LOW_FT)]}
    shed = {"side": 3, "x": [100.0, 100.0 + 8 * PT], "kind": "shed",
            "pitch_deg": math.degrees(math.atan(3 / 12)), "down": 4}
    m = stepped_l(lines)
    sheet = manual.house(m.model_copy(update={"part_roofs": [manual.PartRoofMark(**shed)]}),
                         CFG.data.manual)[0].sheet
    house_roof, wing_roof = sheet.roofs
    assert house_roof == sheet.spec.roof and wing_roof.kind is RoofKind.SHED
    end = sheet.facades[4].side.orientation
    assert wing_roof.down_to is Facing.of(end)
    (slope,) = roof.roofs(sheet).parts[1].slopes
    assert slope.inward == pytest.approx((-end[0], -end[1]))


def test_wrong_roof_marks_are_refused():
    with pytest.raises(manual.BadMarkup, match="крыши частей у дома без частей"):
        manual.house(markup(part_roofs=[{"side": 0, "x": [100.0, 150.0], "kind": "shed",
                                         "pitch_deg": 10.0}]), CFG.data.manual)
    with pytest.raises(ValueError, match="направления ската у неё нет"):
        markup(roof_kind="hip", roof_down=1)


def test_wing_with_two_eaves_marks_waits():
    """На главном крыле карниз и дома, и ниже — ступень внутри крыла, пример не пишется."""
    lines = {1: [(0, 20, EAVE_FT)], 0: [(0, 12, LOW_FT)]}
    with pytest.raises(manual.Unsupported, match="gf#322"):
        manual.house(stepped_l(lines), CFG.data.manual)


def test_house_without_steps_keeps_one_roof_line():
    """Отметки карниза на всех крыльях в пределах допуска от карниза дома — дом без частей."""
    near = EAVE_FT - 0.1
    sample, _ = manual.house(stepped_l({3: [(0, 8, near)], 5: [(20, 28, near)]}), CFG.data.manual)
    assert sample.plan.wings == [] and not any(f.runs for f in sample.sheet.facades)


GABLE_FT = 14.0  # конёк над чистым полом


def drawn(left: dict | None = None) -> Markup:
    """Тот же дом, размеченный целиком (gf#323): у левой стены фронтон до конька, крыша на виде,
    участок карниза и окно во фронтоне; `left` меняет поля левой стены."""
    raw = markup().model_dump(mode="json")
    wall, line = raw["sides"][1]["wall"], pt_y(EAVE_FT)
    raw["sides"][1] |= {
        "outline": [[wall[0], pt_y(-PLINTH_FT)], [wall[0], line], [sum(wall) / 2, pt_y(GABLE_FT)],
                    [wall[1], line], [wall[1], pt_y(-PLINTH_FT)]],
        "roof": [[[wall[0] - 18, line + 9], [sum(wall) / 2, pt_y(GABLE_FT + 1)],
                  [wall[1] + 18, line + 9]]],
        "eaves": [{"x": wall, "y": line, "floors": 1}]} | (left or {})
    raw["sides"][1]["elements"].append({"cls": "window", "box": box(9, 9.5, 2, 2.5)})
    return Markup.model_validate(raw)


def test_drawing_above_eaves_is_cut_as_before():
    """Силуэт, крыша и карниз по участкам не меняют пример: окно во фронтоне срезано по карнизу и
    идёт в счёт срезанного (`data: Стена до карниза в данных`)."""
    plain, dropped = manual.house(markup(), CFG.data.manual)
    full, dropped_full = manual.house(drawn(), CFG.data.manual)
    assert full == plain
    assert dropped_full == dropped + 1


def test_house_with_parts_of_different_height_waits():
    """Участок карниза над другой этажностью по всей стене — части разной высоты, а линии ступени
    нет: пример не пишется (gf#322)."""
    wall = markup().sides[1].wall
    with pytest.raises(manual.Unsupported, match="gf#322"):
        manual.house(drawn({"eaves": [{"x": wall, "y": pt_y(EAVE_FT), "floors": 2}]}),
                     CFG.data.manual)
    beyond = {"x": [wall[0], wall[1] + 2 * PT], "y": pt_y(EAVE_FT), "floors": 1}
    with pytest.raises(manual.BadMarkup, match="за краем стены"):
        manual.house(drawn({"eaves": [beyond]}), CFG.data.manual)


def test_step_inside_rectangle_becomes_virtual_wings():
    """Ступень карниза внутри прямоугольного контура без крыльев (gf#422): сторона меняет отметку
    на 5' от края — контур режется линией ступени, у листа два крыла со своими карнизами."""
    wall = markup().sides[1].wall
    step = {"x": [wall[0], wall[0] + 5 * PT], "y": pt_y(EAVE_FT - 2), "floors": 1}
    sample, _ = manual.house(drawn({"eaves": [step]}), CFG.data.manual)
    assert len(sample.sheet.wings) == 2
    assert sorted(r.eaves_m for f in sample.sheet.facades for r in f.runs) == pytest.approx(
        [ft(PLINTH_FT + EAVE_FT - 2)] * 3 + [ft(PLINTH_FT + EAVE_FT)] * 3)


def test_cut_by_step_has_wall_over_roof_of_lower_part():
    """Разрез по ступени (gf#422): кровля нижней по карнизу части поднимается выше кровли верхней
    (щипец, 3,58 м при карнизе 2,74 м) — над кровлей верхней стоит стена нижней, в данных 3D и в
    IFC; без неё в просмотрщике открытый треугольник неба между скатами."""
    from genfacade import roof
    from genfacade.render.house3d import house_3d
    from genfacade.render.ifc import counts, house_ifc

    wall = markup().sides[1].wall
    step = {"x": [wall[0], wall[0] + 8 * PT], "y": pt_y(EAVE_FT - 1), "floors": 1}
    sheet = manual.house(drawn({"eaves": [step]}), CFG.data.manual)[0].sheet
    house = roof.roofs(sheet)
    low = min(range(len(house.parts)), key=lambda i: house.parts[i].eaves)
    (gable,) = (j for j in roof.joints(house) if j.high == low)  # стена нижней части
    top = max(z for w in gable.walls for *_, z in w)
    assert top > max(p.eaves for p in house.parts) + 0.5
    above = house_3d(sheet, CFG)["roof"]["above"]
    assert any(abs(z - top) < 1e-6 for shape in above for *_, z in shape)
    walls = sum(len(j.walls) for j in roof.joints(house))
    assert counts(house_ifc(sheet, CFG))["IFCWALL"] == len(sheet.facades) + walls


def test_metric_sheet_gives_the_same_house():
    """Российский лист — в метрах (gf#328): те же pt листа с масштабом и отметками в метрах дают
    тот же дом, что в футах."""
    metric = markup(unit="m", pt_per_unit=PT / M_PER_FT, plinth=ft(PLINTH_FT),
                    floor_heights=[ft(EAVE_FT)])
    feet, _ = manual.house(markup(), CFG.data.manual)
    metres, _ = manual.house(metric, CFG.data.manual)
    assert metres.sheet.spec.eaves_m == pytest.approx(feet.sheet.spec.eaves_m)
    for got, want in zip(metres.sheet.facades, feet.sheet.facades, strict=True):
        assert got.side.length_m == pytest.approx(want.side.length_m)
        assert [(x.cls, x.x_m, x.y_m, x.w_m, x.h_m) for x in got.elements] == [
            (x.cls, pytest.approx(x.x_m), pytest.approx(x.y_m), pytest.approx(x.w_m),
             pytest.approx(x.h_m)) for x in want.elements]


def test_side_drawn_at_its_own_scale():
    """Вид стороны в другом масштабе, чем остальные (Texas A&M 2013: север в 3/16", прочие в 1/4"):
    свой `pt_per_unit` стороны даёт тот же дом (gf#323)."""
    raw = markup().model_dump(mode="json")
    left = raw["sides"][1]

    def half(x: float, y: float) -> tuple[float, float]:  # тот же вид вдвое мельче от угла пола
        return 100.0 + (x - 100.0) / 2, FLOOR - (FLOOR - y) / 2

    left["wall"] = [half(x, FLOOR)[0] for x in left["wall"]]
    for el in left["elements"]:
        (x0, top), (x1, bottom) = half(*el["box"][:2]), half(*el["box"][2:])
        el["box"] = [x0, top, x1, bottom]
    left["pt_per_unit"] = PT / 2
    plain, _ = manual.house(markup(), CFG.data.manual)
    scaled, _ = manual.house(Markup.model_validate(raw), CFG.data.manual)
    assert scaled.sheet.facades[1].side.length_m == pytest.approx(ft(20))
    got, want = scaled.sheet.facades[1].elements[0], plain.sheet.facades[1].elements[0]
    box = (want.x_m, want.y_m, want.w_m, want.h_m)
    assert (got.x_m, got.y_m, got.w_m, got.h_m) == pytest.approx(box)


def finished(**changes) -> Markup:
    """Тот же дом с отделкой с листа (gf#245): кирпичный цоколь, карниз под отметкой карниза на
    стороне входа и камень в нижней части левой стены, заходящий за её край."""
    raw = markup().model_dump(mode="json")
    raw["sides"][1]["elements"].append({"cls": "cornice", "box": box(0, EAVE_FT - 0.4, 20, 0.4)})
    raw["sides"][1]["zones"] = [{"role": "accent", "material": "stone", "box": box(-1, 0, 25, 3)}]
    return Markup.model_validate(raw | {"plinth_material": "brick", "trim_material": "wood",
                                        "absent": ["rear: карниза нет — щипцовая стена"]} | changes)


def test_finish_from_markup():
    """Цоколь — зона от земли до чистого пола, основная — от него до карниза, вторая отделка —
    обрезанной по стене, карниз — элемент материалом карниза; палитра — то, что на листе: у
    реального теста не было ни цоколя, ни карниза, и признаки метрики различали эталон по
    самому их наличию (gf#245)."""
    sample, _ = manual.house(finished(), CFG.data.manual)
    sheet, eaves = sample.sheet, ft(PLINTH_FT + EAVE_FT)
    palette = {m.id: m.kind for m in sheet.spec.materials}
    assert palette == {"main": "siding", "plinth": "brick", "trim": "wood", "accent": "stone"}
    front, left = sheet.facades[0], sheet.facades[1]
    assert [(z.role, z.shape[0][1], z.shape[2][1]) for z in front.zones] == [
        ("plinth", 0.0, pytest.approx(ft(PLINTH_FT))),
        ("main", pytest.approx(ft(PLINTH_FT)), pytest.approx(eaves))]
    cornice = next(e for e in left.elements if e.cls is ElementClass.CORNICE)
    assert cornice.material == "trim" and cornice.y_m + cornice.h_m == pytest.approx(eaves)
    accent = left.zones[-1]
    assert accent.role == "accent" and accent.material == "accent"
    assert (accent.shape[0][0], accent.shape[2][0]) == (0.0, pytest.approx(left.side.length_m))
    assert accent.shape[2][1] == pytest.approx(ft(PLINTH_FT + 3))
    assert errors(validate(sheet, CFG.checks)) == []
    bare, _ = manual.house(markup(), CFG.data.manual)           # без отделки на листе — как было
    assert [z.role for z in bare.sheet.facades[0].zones] == ["main"]


def test_one_second_finish_per_house():
    """У палитры одна роль второй отделки: два вида на доме — разметка не собирается."""
    raw = finished().model_dump(mode="json")
    raw["sides"][3]["zones"] = [{"role": "band", "material": "wood", "box": box(0, 4, 20, 0.5)}]
    with pytest.raises(manual.BadMarkup):
        manual.house(Markup.model_validate(raw), CFG.data.manual)


def test_run_writes_samples_and_manifest(tmp_path):
    marks = tmp_path / "markup"
    ffh = marks / "freefarmhouse"  # папка на источник
    ffh.mkdir(parents=True)
    (ffh / "ffh-test.toml").write_text(markup_toml.dumps(markup()))
    three = markup().model_dump()["sides"][:3]
    (ffh / "ffh-crooked.toml").write_text(markup_toml.dumps(markup(id="ffh-crooked", sides=three)))
    (ffh / "ffh-broken.toml").write_text('id = "ffh-broken"\n')  # не разметка: нет сторон
    annex = {"eaves": [{"x": markup().sides[1].wall, "y": pt_y(EAVE_FT - 2), "floors": 1}]}
    annexed = drawn(annex).model_copy(update={"id": "ffh-annex"})
    (ffh / "ffh-annex.toml").write_text(markup_toml.dumps(annexed))
    data = CFG.data.model_copy(update={
        "paths": CFG.data.paths.model_copy(update={"samples_dir": tmp_path / "samples"}),
        "manual": CFG.data.manual.model_copy(update={
            "paths": CFG.data.manual.paths.model_copy(update={"markup_dir": marks})})})
    saved = json.loads(manual.run(CFG.model_copy(update={"data": data})).read_text())
    assert store.ids(tmp_path / "samples", Source.MANUAL) == ["ffh-test"]
    assert saved["cut"] == {"ffh-test": 2}  # фронтон из описи разметчика и навес за карнизом
    # битая разметка — отказ своего дома, остальные собраны (C10, gf#293)
    assert sorted(saved["rejected"]) == ["ffh-broken", "ffh-crooked"]
    assert saved["rejected"]["ffh-broken"].startswith("разметка не читается")
    # дом с частями разной высоты размечен верно — ждёт модуля, а не отказ (gf#323)
    assert list(saved["waiting"]) == ["ffh-annex"]
    assert saved["invalid"] == {}


def _toml(m: Markup) -> str:
    """Разметка обратно в TOML — тем же видом, что пишет разметчик."""
    def value(v: object) -> str:
        if isinstance(v, dict):
            pairs = (f"{k} = {value(x)}" for k, x in v.items() if x is not None)
            return "{ " + ", ".join(pairs) + " }"
        if isinstance(v, list | tuple):
            return "[" + ", ".join(value(x) for x in v) + "]"
        return json.dumps(v, ensure_ascii=False)

    raw = m.model_dump(mode="json", exclude={"sides"})
    head = "".join(f"{k} = {value(v)}\n" for k, v in raw.items() if v is not None)
    sides = "".join("\n[[sides]]\n" + "".join(f"{k} = {value(v)}\n" for k, v in s.items()
                                              if v is not None)
                    for s in m.model_dump(mode="json")["sides"])
    return head + sides


def gabled(*windows: dict) -> Markup:
    """Дом 12' × 20' с окнами на задней (короткой, щипцовой) стене (gf#321)."""
    raw = markup().model_dump(mode="json")
    raw["sides"][2]["elements"] = list(windows)
    return Markup.model_validate(raw)


def test_window_in_the_gable_is_kept_on_the_floor_under_the_roof():
    """`data: Стена до карниза в данных` (gf#321): окно во фронтоне щипцовой стены — целиком в
    стене с фронтоном модуля — остаётся окном этажа под скатом; окно, пересекающее скат, срезано и
    в счёте срезанного; опись считает окна во фронтоне."""
    inside = {"cls": "window", "box": box(5, EAVE_FT + 0.5, 2, 1.5)}
    across = {"cls": "window", "box": box(0.5, EAVE_FT + 0.5, 2, 2)}  # у угла — выше ската
    sample, dropped = manual.house(gabled(inside, across), CFG.data.manual)
    plain, before = manual.house(gabled(), CFG.data.manual)
    [window] = sample.sheet.facades[2].elements
    assert window.floor == sample.sheet.spec.floors + 1
    assert window.y_m == pytest.approx(sample.sheet.spec.eaves_m + ft(0.5))
    assert dropped == before + 1
    assert manual.gable_windows(sample.sheet) == 1
    assert not errors(validate(sample.sheet, CFG.checks))


def test_gable_is_in_the_condition_and_its_window_in_the_answer():
    """`generation: Раскладка — последовательность токенов` (gf#321): у щипцовых стен в условии —
    `<gable>` с вершиной конька в шагах сетки; окно во фронтоне пишется окном этажа под скатом и
    разбирается обратно на то же место."""
    sample, _ = manual.house(gabled({"cls": "window", "box": box(5, EAVE_FT + 0.5, 2, 1.5)}),
                             CFG.data.manual)
    sheet, grid = sample.sheet, CFG.tokens
    cond = tokens.condition(sheet, Mode.BLIND, CFG)
    at = [i for i, t in enumerate(cond) if t == Mark.GABLE]
    rear = sheet.facades[2].side.length_m
    apex = sheet.spec.eaves_m + rear / 2 * math.tan(math.radians(PITCH))
    assert len(at) == 2  # две короткие стены — щипцовые
    assert cond[at[1] + 1:at[1] + 4] == ["1", str(tokens.units(rear / 2, grid)),
                                         str(tokens.units(apex, grid))]
    words = tokens.answer(sheet, Mode.BLIND, CFG)
    [window] = tokens.decode(words, tokens.bare(sheet), CFG).facades[2].elements
    assert window.floor == sheet.spec.floors + 1
    assert window.y_m == pytest.approx(tokens.metres(tokens.units(
        sheet.facades[2].elements[0].y_m, grid), grid))


def test_gable_window_is_not_a_storey():
    """Окно во фронтоне (gf#321) — не этаж: этажность по окнам цела, свод этажей его не видит."""
    sample, _ = manual.house(gabled({"cls": "window", "box": box(5, EAVE_FT + 0.5, 2, 1.5)}),
                             CFG.data.manual)
    assert measures.floors_kept(sample.sheet)
    assert not measures.storeys(sample.sheet).facades[2].elements


def _sheet_of(path: str):
    sample, _ = manual.house(manual.read(Path(path)), CFG.data.manual)
    return sample.sheet


def test_real_houses_keep_the_doors_drawn_from_the_plans():
    # gf#414: дверь западной веранды southern и остеклённый вход ghent — в собранном листе
    # (лист из снимка до слияния разметки их не имел, хозяин видел дом без двери)
    south = _sheet_of("markup/freefarmhouse/ffh-southern.toml")
    west = [x for x in south.facades[1].elements if x.cls == ElementClass.DOOR]
    assert [x.variant.kind for x in west] == ["transom"]
    ghent = _sheet_of("markup/solar-decathlon/sd-ghent-2011.toml")
    doors = [x for f in ghent.facades for x in f.elements if x.cls == ElementClass.DOOR]
    assert [x.variant.kind for x in doors] == ["glazed"]
    assert not [x for x in ghent.facades[0].elements if x.cls == ElementClass.WINDOW]


def real(house_id: str) -> Markup:
    """Настоящая разметка из `markup/` репозитория."""
    root = Path(__file__).parents[2] / "markup"
    return next(m for p in sorted(root.glob("*/*.toml")) if (m := manual.read(p)).id == house_id)


def test_real_step_without_wings_is_cut_into_parts():
    """ffh-julie: контур прямоугольный, задние 3,05 м — один этаж (gf#422): два виртуальных крыла,
    задняя часть ниже; карниз дома — над двумя этажами."""
    sample, _ = manual.house(real("ffh-julie"), CFG.data.manual)
    rear = sorted(sample.sheet.wings, key=lambda w: w.y0_m)[0]
    assert len(sample.sheet.wings) == 2 and rear.y1_m - rear.y0_m == pytest.approx(3.05, abs=0.05)
    assert sorted({(r.floors, round(r.eaves_m, 2)) for f in sample.sheet.facades
                   for r in f.runs}) == [(1, 3.1), (2, 4.11)]


def test_real_marilyn_has_three_tiers_and_penny_cuts_a_wing():
    """ffh-marilyn: две линии ступени (4,79 и 4,88 м — одна) — три части; ffh-penny-sylvia: крыло
    задних модулей режется по x ≈ 6,15, у главного крыла и карниза дома — своё."""
    marilyn, _ = manual.house(real("ffh-marilyn"), CFG.data.manual)
    assert len(marilyn.sheet.wings) == 3
    penny, _ = manual.house(real("ffh-penny-sylvia"), CFG.data.manual)
    assert len(penny.sheet.wings) == 3
    cut = sorted(w.x1_m - w.x0_m for w in penny.sheet.wings)[:2]
    assert sum(cut) == pytest.approx(9.81 - 2.53, abs=0.05)
    assert min(cut) == pytest.approx(3.6, abs=0.1)


def test_real_roof_marks_are_not_eaves():
    """sd-nyalfred-2015: высокий край односкатной — не карниз, карниз дома — низкий (3,37 м),
    дом без частей; sd-northwestern-2017: полоса панелей над плоской кровлей — не карниз."""
    nyalfred, _ = manual.house(real("sd-nyalfred-2015"), CFG.data.manual)
    assert nyalfred.sheet.spec.eaves_m == pytest.approx(3.37, abs=0.02)
    assert not nyalfred.sheet.wings and not any(f.runs for f in nyalfred.sheet.facades)
    northwestern, cut = manual.house(real("sd-northwestern-2017"), CFG.data.manual)
    assert northwestern.sheet.spec.eaves_m == pytest.approx(4.07, abs=0.02) and cut > 0


def test_all_real_houses_are_built_and_old_ones_without_fallbacks():
    """59 разметок — 59 листов (gf#422); 49 прежних собираются по отметкам как есть (без `_bare` и
    разрезов), поэтому их карниз, участки и крылья прежние."""
    root = Path(__file__).parents[2] / "markup"
    fallback = {"ffh-julie", "ffh-virginia-ext", "ffh-marilyn", "ffh-penny-sylvia", "sd-va-2011",
                "sd-maryland-2017", "sd-nyalfred-2015", "sd-northwestern-2017", "sd-sit-2013",
                "sd-wvu-2013"}
    built = 0
    for path in sorted(root.glob("*/*.toml")):
        m = manual.read(path)
        manual.house(m, CFG.data.manual)
        built += 1
        if m.id not in fallback:
            manual._house(m, CFG.data.manual, False)
    assert built == 59
