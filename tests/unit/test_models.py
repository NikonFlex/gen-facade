"""Стабы моделей шагов 1 и 4 (genfacade/models/stub.py, gf#60)."""

import json
import os
import subprocess
import sys
from xml.etree import ElementTree

import pytest

from genfacade.config import SpecStub
from genfacade.models import finish, stub
from genfacade.models.stub import LayoutContext, ModelError
from genfacade.render import sheet_format
from genfacade.render.svg import paint, pen_for, sheet_svg
from genfacade.schema import (
    CasingKind,
    ElementClass,
    FacadeSheet,
    Material,
    Mode,
    PaletteRole,
    RoofKind,
    ShutterKind,
    ZoneRole,
)


@pytest.mark.parametrize(("text", "floors"), [
    ("A simple one-storey house with a flat roof.", 1),
    ("A Two-Storey villa.", 2),
    ("Двухэтажный коттедж", 2),
    ("A three-story house, not a bungalow", 3),   # слово раньше других
    ("Five-storey apartment block.", 1),          # слова нет — как у заготовки
    ("", 1),
])
def test_spec_stub_floors_from_text(cfg, text, floors):
    """`generation: Стаб шага 1`: из текста — этажность, стиль и отделка; остальное — заготовка:
    плоская крыша, палитра по ролям, высота этажа одна, карниз над последним этажом."""
    spec, base = stub.spec_model(text, cfg.models.spec), stub.spec_model("", cfg.models.spec)
    assert (spec.floors, spec.roof.kind) == (floors, RoofKind.FLAT)
    assert [m.id for m in spec.materials] == ["main", "plinth", "accent", "trim", "roof"]
    assert spec.floor_heights_m == base.floor_heights_m * floors
    assert spec.eaves_m == pytest.approx(spec.plinth_m + floors * base.floor_heights_m[0])
    same = {k: getattr(base, k) for k in ("floors", "floor_heights_m", "eaves_m", "materials",
                                          "trim", "style")}
    assert spec.model_copy(update=same) == base


def test_spec_stub_style_from_text(cfg):
    """Стиль — по слову в тексте, нет слова — стиль заготовки; отделка без слов — из тех, что
    подходят стилю (`generation: Отделка без слов — от текста`)."""
    rules = cfg.models.spec
    for text in ("A classic house", "A classic two-storey house", "Классический дом у реки"):
        spec = stub.spec_model(text, rules)
        assert spec.style == "classic"
        assert spec.style in rules.finish[finish.look(text, spec.style, rules).finish].styles
    assert stub.spec_model("A house", rules).style == stub.spec_model("", rules).style


def test_finish_library_is_consistent(cfg):
    """Библиотека отделок: не меньше восьми, виды материалов — из library.toml, стили — те,
    что знает модель шага 4, у каждого стиля и вида стен из слов текста есть отделка."""
    rules = cfg.models.spec
    assert len(rules.finish) >= 8
    kinds = {m.kind for f in rules.finish.values() for m in f.materials.values()}
    assert kinds <= set(cfg.library.kinds)
    assert {s for f in rules.finish.values() for s in f.styles} == set(cfg.synthetic.spec.styles)
    assert set(rules.style_words) == set(cfg.synthetic.spec.styles)
    walls = {f.materials[PaletteRole.MAIN].kind for f in rules.finish.values()}
    assert set(rules.material_words) <= walls


def test_finish_typo_is_a_load_error(cfg):
    """Опечатка в имени цвета ряда или нехватка роли палитры — ошибка загрузки настроек."""
    raw = cfg.models.spec.model_dump(mode="json")
    typo = json.loads(json.dumps(raw))
    typo["finish"]["brick_red"]["materials"]["main"]["colors"][0] = "brik_red"
    with pytest.raises(ValueError, match="нет цветов в ряду colors"):
        SpecStub(**typo)
    short = json.loads(json.dumps(raw))
    del short["finish"]["brick_red"]["materials"]["roof"]
    with pytest.raises(ValueError, match="роли"):
        SpecStub(**short)


def test_brick_house_with_white_casings(cfg):
    """`generation: Отделка по словам текста`, `Элемент, названный в тексте`: стены — кирпич,
    обрамление белое, наличники есть; у светлого кирпича их по умолчанию нет."""
    rules, white = cfg.models.spec, cfg.models.spec.colors["white"].hex
    for text in ("кирпичный дом с белыми наличниками", "A brick house with white window casings"):
        spec = stub.spec_model(text, rules)
        assert _palette(spec)["main"].kind == "brick"
        assert _palette(spec)["trim"].color == white
        assert spec.trim.casing is not CasingKind.NONE
    assert stub.spec_model("Светлый кирпичный коттедж", rules).trim.casing is CasingKind.NONE


@pytest.mark.parametrize(("text", "wanted"), [
    ("A classic yellow house with green shutters", {"main": "yellow", "trim": "green"}),
    ("Белый дом с обшивкой и чёрными ставнями", {"main": "white", "trim": "black"}),
    ("Серый дом с красной крышей", {"main": "grey", "roof": "red"}),
    ("A wooden house with a dark plinth", {"plinth": "graphite"}),
])
def test_color_goes_to_the_part_it_stands_before(cfg, text, wanted):
    """Цвет красит часть, чьё название за ним; без названия — стены."""
    rules = cfg.models.spec
    pal = _palette(stub.spec_model(text, rules))
    assert {role: pal[role].color for role in wanted} \
        == {role: rules.colors[name].hex for role, name in wanted.items()}


def test_color_outside_the_kind_row_does_not_paint_walls(cfg):
    """Кирпич не бывает синим: цвет стен — из ряда цветов вида, цвет вне ряда не берётся."""
    rules = cfg.models.spec
    main = _palette(stub.spec_model("A blue brick house", rules))["main"]
    brick = {rules.colors[c].hex for f in rules.finish.values()
             if f.materials[PaletteRole.MAIN].kind == "brick"
             for c in f.materials[PaletteRole.MAIN].colors}
    assert (main.kind, main.color in brick) == ("brick", True)


def test_named_element_is_put_and_no_removes_it(cfg):
    rules = cfg.models.spec
    assert stub.spec_model("A classic house, no shutters", rules).trim.shutters is ShutterKind.NONE
    assert stub.spec_model("A classic house", rules).trim.shutters is not ShutterKind.NONE
    assert stub.spec_model("Современный дом со ставнями", rules).trim.shutters \
        is not ShutterKind.NONE


TEXTS = ["A house in the forest", "Cozy cottage by the lake", "Дом для семьи из четырёх человек",
         "Large villa with a garden", "A small house near the sea", "Уютный коттедж",
         "Family home, quiet street", "House with a terrace", "Загородный дом", "Country house"]


def test_same_text_same_house_in_any_process(cfg):
    """`generation: Отделка без слов — от текста`: тот же текст — тот же дом, и не из-за случайного
    `hash()` процесса: два процесса с разным PYTHONHASHSEED дают тот же дом."""
    rules = cfg.models.spec
    assert all(stub.spec_model(t, rules) == stub.spec_model(t, rules) for t in TEXTS)
    code = ("import json, sys; from genfacade import config; from genfacade.models import stub; "
            "c = config.load(); print(json.dumps([stub.spec_model(t, c.models.spec)"
            ".model_dump_json() for t in json.loads(sys.argv[1])]))")
    runs = {seed: subprocess.run([sys.executable, "-c", code, json.dumps(TEXTS)], check=True,  # noqa: S603
                                 capture_output=True, text=True, env=os.environ | {
                                     "PYTHONHASHSEED": seed}).stdout for seed in ("1", "2")}
    here = json.dumps([stub.spec_model(t, rules).model_dump_json() for t in TEXTS])
    assert runs["1"].strip() == runs["2"].strip() == here


def test_texts_without_words_give_different_finishes(cfg):
    """Дома однотипны не должны быть: десять описаний без слов отделки — не меньше трёх отделок,
    у одной отделки больше одного цвета стен, цвета — только из ряда отделки или из библиотеки."""
    rules = cfg.models.spec
    looks = [finish.look(t, stub.spec_model(t, rules).style, rules) for t in TEXTS]
    colors = {}
    for look in looks:
        colors.setdefault(look.finish, set()).add(_palette(look)["main"].color)
    assert len(colors) >= 3 and max(len(c) for c in colors.values()) >= 2
    palette = {c.hex for c in rules.colors.values()}
    assert {m.color for look in looks for m in look.materials} <= palette | {None}


def test_one_palette_on_all_walls(cfg, lay_out):
    """`facade: Общие параметры дома`: основная отделка всех четырёх стен — один материал одного
    цвета, тот, что задан палитрой дома."""
    sheet = lay_out(text="Кирпичный дом")
    root = ElementTree.fromstring(sheet_svg(sheet, cfg))
    mains = [z for z in root.iter() if z.tag.endswith("polygon")
             and z.get(sheet_format.ROLE) == ZoneRole.MAIN]
    assert len(mains) >= 4
    # кирпич — рисунком цвета палитры (gf#304), штукатурка — самим цветом: заливка одна на все стены
    assert {z.get("fill") for z in mains} == {paint("main", pen_for(sheet, cfg))}
    assert {z.get(sheet_format.MATERIAL) for z in mains} == {"main"}


def _palette(house) -> dict[str, Material]:
    """Палитра по ролям: у дома (HouseSpec) и у отделки (finish.Look) материалы одним полем."""
    return {m.id: m for m in house.materials}


def _unfixed(elements):
    return [e.model_copy(update={"fixed": []}) for e in elements]


def _fixed(sheet):
    return sorted(e.cls for f in sheet.facades for e in f.elements if e.fixed)


def test_layout_stub_same_facades_in_both_modes(lay_out):
    """Стаб шага 4: заготовка простого дома, одна раскладка на оба режима; режимы отличаются
    только тем, что задано условием (`facade: Проёмы плана — условие`)."""
    plan_mode, blind = lay_out(Mode.WITH_OPENINGS), lay_out(Mode.BLIND)
    for a, b in zip(plan_mode.facades, blind.facades, strict=True):
        assert (_unfixed(a.elements), a.zones) == (_unfixed(b.elements), b.zones)
    windows = [e.w_m for f in blind.facades for e in f.elements if e.cls is ElementClass.WINDOW]
    assert sorted(windows) == [1.0, 1.2, 1.5, 2.0]  # окна простого дома — разного размера
    FacadeSheet.model_validate(blind.model_dump())  # материалы — из палитры стаба шага 1


def test_layout_stub_fixes_only_plan_openings(lay_out):
    """В глухом режиме окна плана заделаны — задан условием только вход; в «окна из плана» —
    все пять проёмов (`generation: Режимы отличаются входом`)."""
    assert _fixed(lay_out(Mode.BLIND)) == [ElementClass.DOOR]
    assert _fixed(lay_out(Mode.WITH_OPENINGS)) == [ElementClass.DOOR] + [ElementClass.WINDOW] * 4


def test_layout_stub_rejects_unknown_wall(lay_out, cfg):
    wall = lay_out().facades[1]
    longer = wall.model_copy(update={"side": wall.side.model_copy(update={"length_m": 7.0})})
    with pytest.raises(ModelError, match="стаб знает только простой дом"):
        house = stub.spec_model("", cfg.models.spec)
        stub.layout_model(longer, LayoutContext(house, Mode.WITH_OPENINGS, ""))


def test_layout_stub_rejects_other_number_of_walls(lay_out):
    sheet = lay_out()
    three = sheet.model_copy(update={"facades": sheet.facades[:3]})
    with pytest.raises(ModelError, match="из 4 стен, а у плана их 3"):
        stub.layout_all(three, LayoutContext(sheet.spec, Mode.WITH_OPENINGS, ""))
