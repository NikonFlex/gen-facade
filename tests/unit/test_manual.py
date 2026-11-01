"""Ручная разметка реальных коттеджей → примеры теста (`data: Реальные коттеджи — тест`,
`data: Стена до карниза в данных`): прямоугольники в pt листа → элементы в метрах от земли;
контур — ортогональный, с внутренними углами (gf#199)."""

import json

import pytest

from genfacade import config
from genfacade.datasets import manual, store
from genfacade.datasets.manual import M_PER_FT, Markup
from genfacade.schema import ElementClass, Mode, OpeningKind, Source, Split, Trim
from genfacade.train import tokens
from genfacade.validate import errors, validate

CFG = config.load()
PT = 18.0       # pt на фут: лист 1/4" = 1'-0"
FLOOR = 500.0   # отметка чистого пола на листе, pt
PLINTH_FT, EAVE_FT = 1.0, 8.0   # пол над землёй и карниз над полом, футы


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
    raw = {"id": "ffh-test", "pdf": "test.pdf", "roof": "двускатная", "pt_per_ft": PT,
           "material": "siding", "plinth_ft": PLINTH_FT, "floor_heights_ft": [EAVE_FT],
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


def test_l_shaped_house(tmp_path):
    """Г-образный дом (gf#199): фасад 12', бок 20', тыл 6', внутренний угол, бок крыла 8', тыл
    крыла 6', другой бок 28' — шесть сторон; план замкнут, лист проходит валидатор."""
    l_sides = [side("FRONT", 12, {"cls": "door", "box": box(5, 0, 2, 6.75)}),
               side("LEFT", 20), side("REAR WING", 6) | {"inner_corner": True},
               side("WING SIDE", 8), side("REAR", 6), side("RIGHT", 28)]
    sample, _ = manual.house(markup(sides=l_sides), CFG.data.manual)
    lengths = [f.side.length_m for f in sample.sheet.facades]
    assert lengths == pytest.approx([ft(v) for v in (12, 20, 6, 8, 6, 28)])
    assert len(sample.plan.outline) == 6 and len(sample.plan.walls) == 6
    assert errors(validate(sample.sheet, CFG.checks)) == []


def finished(**changes) -> Markup:
    """Тот же дом с отделкой с листа (gf#245): кирпичный цоколь, карниз под отметкой карниза на
    стороне входа и камень в нижней части левой стены, заходящий за её край."""
    raw = markup().model_dump(mode="json")
    raw["sides"][0]["elements"].append({"cls": "cornice", "box": box(0, EAVE_FT - 0.75, 12, 0.75)})
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
    cornice = next(e for e in front.elements if e.cls is ElementClass.CORNICE)
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
    (ffh / "ffh-test.toml").write_text(_toml(markup()))
    three = markup().model_dump()["sides"][:3]
    (ffh / "ffh-crooked.toml").write_text(_toml(markup(id="ffh-crooked", sides=three)))
    data = CFG.data.model_copy(update={
        "paths": CFG.data.paths.model_copy(update={"samples_dir": tmp_path / "samples"}),
        "manual": CFG.data.manual.model_copy(update={
            "paths": CFG.data.manual.paths.model_copy(update={"markup_dir": marks})})})
    saved = json.loads(manual.run(CFG.model_copy(update={"data": data})).read_text())
    assert store.ids(tmp_path / "samples", Source.MANUAL) == ["ffh-test"]
    assert saved["cut"] == {"ffh-test": 2}  # фронтон из описи разметчика и навес за карнизом
    assert list(saved["rejected"]) == ["ffh-crooked"]
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
    sides = "".join("\n[[sides]]\n" + "".join(f"{k} = {value(v)}\n" for k, v in s.items())
                    for s in m.model_dump(mode="json")["sides"])
    return head + sides
