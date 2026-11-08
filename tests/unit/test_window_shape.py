"""Форма окна — вид проёма (gf#319, `facade: Элемент — класс и прямоугольник`, `facade: Элементы
в SVG`): рамка остаётся прямоугольником, контур по виду считает window_shape.py; лист, разбор
листа и дом объёмом — на каждом виде окна."""

import shapely
from test_roof import CFG, _with_window, bare

from genfacade import roof, window_shape
from genfacade.render.house3d import house_3d
from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg
from genfacade.schema import (
    DOOR_KINDS,
    Element,
    ElementClass,
    OpeningVariant,
    RoofKind,
    VariantKind,
)
from genfacade.unfold import unfold
from genfacade.validate import validate

WINDOW_KINDS = [k for k in VariantKind if k not in DOOR_KINDS]
SHAPED = (VariantKind.SLOPE, VariantKind.ARCH, VariantKind.OVAL)


def _gabled(kind: VariantKind, top: float = 0.6):
    """Дом с двускатной крышей и окном вида kind во фронтоне по оси конька, верх — на top над
    карнизом (у `slope` выше ската — рамка через скат)."""
    sheet = unfold(bare(RoofKind.GABLE))
    k = next(i for i, a in enumerate(roof.gables(sheet)) if a is not None)
    mid, eaves = sheet.facades[k].side.length_m / 2, sheet.spec.eaves_m
    sheet = _with_window(sheet, k, mid - 0.5, eaves + 0.1, 1.0, top - 0.1)
    variant = OpeningVariant(kind=kind, cols=2, rows=2)
    facades = list(sheet.facades)
    facades[k] = facades[k].model_copy(update={"elements": [
        facades[k].elements[0].model_copy(update={"variant": variant})]})
    return sheet.model_copy(update={"facades": facades}), k


def test_every_window_kind_draws_parses_and_stands_in_3d():
    """Каждый вид окна рисуется на листе и разбирается обратно тем же элементом; не прямоугольный
    — контуром `window-shape`; в 3D окно во фронтоне — многоугольником контура."""
    for kind in WINDOW_KINDS:
        sheet, k = _gabled(kind)
        text = sheet_svg(sheet, CFG)
        [window] = parse_sheet_svg(text)[k][0]
        assert window == sheet.facades[k].elements[0], kind
        shaped = 'class="window-shape"' in text
        assert shaped == (kind in (VariantKind.ARCH, VariantKind.OVAL)), kind
        [glass] = house_3d(sheet, CFG)["roof"]["windows"]
        assert len(glass) > 4 if kind in (VariantKind.ARCH, VariantKind.OVAL) else len(glass) == 4


def test_slope_window_is_cut_by_the_slope():
    """Окно по скату: рамка выходит за скат, контур — рамка, срезанная скатом с отступом; валидатор
    проверяет контур — ни `outside`, ни `slope`; прямоугольное окно с той же рамкой — брак."""
    sheet, k = _gabled(VariantKind.SLOPE, top=2.5)
    above = roof.gables(sheet)[k]
    room = roof.room(sheet.facades[k].side.length_m, sheet.spec.eaves_m, above,
                     CFG.checks.slope_offset_m)
    [window] = sheet.facades[k].elements
    shape = shapely.Polygon(window_shape.outline(window, room))
    assert room.buffer(1e-9).contains(shape) and 4 < len(window_shape.outline(window, room)) <= 6
    assert not [v for v in validate(sheet, CFG.checks) if v.side == k and v.element == "g1"]
    plain = sheet.model_copy(update={"facades": [
        f.model_copy(update={"elements": [e.model_copy(update={"variant": None})
                                          for e in f.elements]}) for f in sheet.facades]})
    assert {v.rule for v in validate(plain, CFG.checks) if v.element == "g1"}
    assert 'class="window-shape"' in sheet_svg(sheet, CFG)


def test_arch_and_round_outlines_stay_in_the_frame():
    window = Element(id="w", cls=ElementClass.WINDOW, x_m=1.0, y_m=1.0, w_m=1.2, h_m=1.5)
    frame = shapely.box(1.0, 1.0, 2.2, 2.5).buffer(1e-9)
    for kind in SHAPED[1:]:
        shaped = window.model_copy(update={"variant": OpeningVariant(kind=kind)})
        outline = shapely.Polygon(window_shape.outline(shaped))
        assert frame.contains(outline) and outline.area < 1.2 * 1.5, kind
