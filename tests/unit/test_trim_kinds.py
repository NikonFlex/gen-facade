"""Виды выводимых элементов (gf#318, `facade: Вид выводимых элементов — один на дом`, `Виды двери`):
вид — запись config/derive.toml; каждый вид каждого элемента рисуется на листе и в 3D, а новый вид
не меняет ни слов условия модели, ни её словаря."""

import pytest

from genfacade import config, derive
from genfacade.datasets.synthetic import build
from genfacade.models import stub
from genfacade.render.house3d import house_3d
from genfacade.render.svg import sheet_svg
from genfacade.schema import DOOR_KINDS, ElementClass, FacadeSheet, HouseTrim, Trim, VariantKind
from genfacade.train import tokens

ELEMENTS = ("sill", "casing", "shutters", "canopy", "door")  # поля HouseTrim с видом


def _rich(cfg) -> FacadeSheet:
    """Синтетический дом, где есть подоконник, наличник, ставни, козырёк и дверь со стеклом."""
    for seed in range(200):
        sheet = build.sample(seed, cfg).sheet
        has = {e.cls for f in sheet.facades for e in f.elements}
        glazed = any(e.variant and e.variant.kind in DOOR_KINDS for f in sheet.facades
                     for e in f.elements if e.cls is ElementClass.DOOR)
        want = {ElementClass.SILL, ElementClass.MOLDING, ElementClass.BLIND, ElementClass.CANOPY}
        if want <= has and glazed:
            return sheet
    raise AssertionError("в 200 синтетических домах нет дома со всеми выводимыми элементами")


def _with_kind(sheet: FacadeSheet, element: str, kind: str, cfg) -> FacadeSheet:
    """Тот же дом с другим видом одного элемента: выведенные прямоугольники пересчитаны по виду."""
    spec = sheet.spec.model_copy(update={"trim": sheet.spec.trim.model_copy(
        update={element: kind})})
    facades = []
    for f in sheet.facades:
        wall = derive.Wall(spec, f.side.length_m, cfg.derive)
        placed = derive.place(derive.base(f.elements), derive.flags(f.elements), wall)
        facades.append(f.model_copy(update={"elements": placed}))
    return sheet.model_copy(update={"spec": spec, "facades": facades})


CASES = [(element, kind) for element in ELEMENTS for kind in config.load().derive.kinds(element)]


@pytest.mark.parametrize(("element", "kind"), CASES)
def test_every_kind_is_drawn_on_sheet_and_in_3d(cfg, element, kind):
    """Каждый вид каждого элемента рисуется на листе (SVG) и собирается для дома объёмом (3D) без
    ошибки, а вид с контуром (сандрик, свод, столбы) рисует свой контур."""
    sheet = _with_kind(_rich(cfg), element, kind, cfg)
    svg = sheet_svg(sheet, cfg)
    assert "<svg" in svg
    walls = house_3d(sheet, cfg)["walls"]
    assert len(walls) == len(sheet.facades)
    shape = cfg.derive.look(element, kind).shape
    if element in ("sill", "canopy"):  # форму 3D строит просмотр по имени формы
        got = {b["shape"] for w in walls for b in w["relief"] if b["cls"] and b["shape"]}
        assert shape in got


def test_kind_changes_the_picture_not_only_the_name(cfg):
    """Вид виден на листе: два разных вида одного элемента дают разный SVG."""
    sheet = _rich(cfg)
    for element in ELEMENTS:
        pictures = {sheet_svg(_with_kind(sheet, element, kind, cfg), cfg)
                    for kind in cfg.derive.kinds(element)}
        assert len(pictures) == len(cfg.derive.kinds(element)), element


def test_unknown_kind_is_refused_with_its_name(cfg):
    sheet = _with_kind(_rich(cfg), "sill", "flat", cfg)
    bad = sheet.model_copy(update={"spec": sheet.spec.model_copy(update={
        "trim": HouseTrim(sill="unseen", canopy="flat")})})
    assert bad.spec.trim.sill == "unseen"
    with pytest.raises(ValueError, match="unseen"):
        cfg.derive.look("sill", "unseen")
    assert cfg.derive.unknown(bad.spec.trim) == ["sill=unseen"]


def test_condition_has_only_presence_of_trim(cfg):
    """Условие модели несёт у выводимого элемента «есть / нет», а не вид: дом с любым видом пишется
    теми же токенами, что дом с другим видом (gf#318)."""
    sheet = _rich(cfg)
    a = tokens.condition(_with_kind(sheet, "shutters", "panel", cfg), tokens.Mode.BLIND, cfg)
    other = _with_kind(sheet, "shutters", "board_batten_z", cfg)
    b = tokens.condition(other, tokens.Mode.BLIND, cfg)
    assert a == b
    none = tokens.condition(_with_kind(sheet, "shutters", "none", cfg), tokens.Mode.BLIND, cfg)
    assert none != a and "has:no" in none
    assert not any(t.startswith(("sill_kind:", "casing_kind:", "shutters_kind:", "canopy_kind:"))
                   for t in tokens.vocabulary(cfg))


def test_vocabulary_does_not_depend_on_kinds(cfg, tmp_path):
    """Новый вид — запись конфига: словарь модели (а с ним и обученный чекпойнт) тот же."""
    folder = tmp_path / "cfg"
    folder.mkdir()
    (folder / "derive.toml").write_text(
        '[shutters.test_lace]\nshape = "louver"\nshare = 0.4\n'
        '[canopy.test_wide]\nshape = "posts"\npad_m = 0.6\ngap_m = 0.05\nheight_m = 0.2\n')
    grown = config.load(folder)
    assert "test_lace" in grown.derive.shutters
    assert tokens.vocabulary(grown) == tokens.vocabulary(cfg)
    sheet = _with_kind(_rich(grown), "shutters", "test_lace", grown)
    assert sheet_svg(sheet, grown)  # и рисуется, и считается без правки кода


def test_text_names_a_kind(cfg):
    """Слово вида в тексте ставит элемент этого вида (`generation: Элемент, названный в тексте`)."""
    rules = cfg.models.spec
    got = stub.spec_model("Кирпичный дом с арочным козырьком и сандриками над окнами", rules).trim
    assert (got.canopy, got.casing) == ("arched", "pediment")
    assert stub.spec_model("A house with six-panel door and louvered shutters", rules).trim.door \
        == "panel6"
    assert stub.spec_model("A house with louvered shutters", rules).trim.shutters == "louvered"


def test_door_leaf_does_not_decide_glazing(cfg):
    """Рисунок полотна — вид дома (дверь `door`), остекление — вариант элемента, который ставит
    модель: смена вида полотна не меняет варианты дверей и число элементов."""
    sheet = _rich(cfg)
    doors = [(e.id, e.variant) for f in sheet.facades for e in f.elements
             if e.cls is ElementClass.DOOR]
    for kind in cfg.derive.kinds("door"):
        other = _with_kind(sheet, "door", kind, cfg)
        assert [(e.id, e.variant) for f in other.facades for e in f.elements
                if e.cls is ElementClass.DOOR] == doors
    assert {v.kind for _, v in doors if v} <= set(DOOR_KINDS) | {VariantKind.REGULAR}


def test_trim_enum_matches_derive_fields():
    """Признаки модели (Trim) и поля вида дома (HouseTrim) — одни и те же элементы, плюс дверь."""
    assert {t.value for t in Trim} | {"door"} == set(HouseTrim.model_fields)


def _drawn(cfg, element: str, kind: str):
    """Рисунок одного вида на элементе 1 × 0,4 м: узлы SVG, которые он добавил."""
    from xml.etree import ElementTree  # noqa: PLC0415 — только для этого теста

    from genfacade.render import trim  # noqa: PLC0415
    from genfacade.schema import Element  # noqa: PLC0415
    e = Element(id="k", cls=ElementClass.CANOPY, x_m=0.0, y_m=2.0, w_m=1.0, h_m=0.4)
    g = ElementTree.Element("g")
    look = cfg.derive.look(element, kind)
    return trim.canopy(g, e, look, cfg.sheet.trim, 0.0)


def test_shapes_draw_their_own_contour(cfg):
    """Свод — многоугольник из дуги, навес на столбах — плита и два столба до низа двери, а не
    запасной рисунок другой формы."""
    arch = _drawn(cfg, "canopy", "arched")
    assert arch.tag == "polygon" and len(arch.attrib["points"].split()) > 10
    posts = _drawn(cfg, "canopy", "posts")
    heights = sorted(float(r.attrib["height"]) for r in posts.iter("rect"))
    assert len(heights) == 3 and heights[-1] > 1.9  # столб — от низа двери (0) до плиты
