"""Ручная разметка реальных коттеджей → примеры теста (`data: Реальные коттеджи — тест`,
`data: Стена до карниза в данных`): прямоугольники в pt листа → элементы в метрах от земли."""

import json

import pytest

from genfacade import config
from genfacade.datasets import manual, store
from genfacade.datasets.manual import M_PER_FT, Markup
from genfacade.schema import ElementClass, OpeningKind, Source, Split
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


def test_opposite_sides_must_match():
    sides = markup().model_dump()["sides"]
    sides[2] = side("REAR", 14)  # тыл на 2' длиннее фасада
    with pytest.raises(manual.NotRectangle, match="стороны 0 и 2"):
        manual.house(markup(sides=sides), CFG.data.manual)


def test_run_writes_samples_and_manifest(tmp_path):
    marks = tmp_path / "markup"
    marks.mkdir()
    (marks / "ffh-test.toml").write_text(_toml(markup()))
    three = markup().model_dump()["sides"][:3]
    (marks / "ffh-crooked.toml").write_text(_toml(markup(id="ffh-crooked", sides=three)))
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
    head = "".join(f"{k} = {value(v)}\n" for k, v in raw.items())
    sides = "".join("\n[[sides]]\n" + "".join(f"{k} = {value(v)}\n" for k, v in s.items())
                    for s in m.model_dump(mode="json")["sides"])
    return head + sides
