"""Форма окна — вид проёма (gf#319, `facade: Элемент — класс и прямоугольник`, `facade: Элементы
в SVG`): рамка остаётся прямоугольником, контур по виду считает window_shape.py; лист, разбор
листа и дом объёмом — на каждом виде окна."""

import math

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
    Rule,
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
    gable = window_shape.gable_room(sheet.facades[k].side.length_m, sheet.spec.eaves_m, above,
                                    CFG.checks.slope_offset_m)
    [window] = sheet.facades[k].elements
    shape = shapely.Polygon(window_shape.outline(window, gable))
    assert gable.room.buffer(1e-9).contains(shape)
    assert 4 < len(window_shape.outline(window, gable)) <= 6
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


def test_slope_window_with_most_of_the_frame_behind_the_slope_is_a_defect():
    """Окно `slope` (gf#319): контур — не меньше `slope_share` рамки; рамка почти целиком за
    скатом — брак `slope`, тот же порог, что у стража."""
    sheet, k = _gabled(VariantKind.SLOPE, top=2.5)
    [window] = sheet.facades[k].elements
    far = window.model_copy(update={"x_m": 0.05, "y_m": sheet.spec.eaves_m + 0.1})
    facades = list(sheet.facades)
    facades[k] = facades[k].model_copy(update={"elements": [far]})
    bad = sheet.model_copy(update={"facades": facades})
    assert any(v.rule is Rule.SLOPE and "за скатом" in v.message
               for v in validate(bad, CFG.checks) if v.element == "g1")
    assert not any("за скатом" in v.message for v in validate(sheet, CFG.checks))


# Окно по скату gf#470 (`facade: Окно по скату`): стена 6 м, карниз 3 м, скат 35°, конёк по оси.
TAN = math.tan(math.radians(35))
RIDGE = 3.0 + 3.0 * TAN
GABLE = window_shape.gable_room(6.0, 3.0, [(0.0, 3.0), (6.0, 3.0), (3.0, RIDGE)], 0.2)


def _slope_outline(x: float, y: float, w: float, h: float) -> list[tuple[float, float]]:
    window = Element(id="w", cls=ElementClass.WINDOW, x_m=x, y_m=y, w_m=w, h_m=h,
                     variant=OpeningVariant(kind=VariantKind.SLOPE))
    return window_shape.outline(window, GABLE)


def _same(shape, want) -> bool:
    """Те же вершины с точностью 0,01 м (начало обхода не важно)."""
    return len(shape) == len(want) and shapely.Polygon(shape).symmetric_difference(
        shapely.Polygon(want)).area < 1e-4 and all(
        min(math.dist(p, q) for q in shape) < 0.01 for p in want)


def test_slope_window_beside_the_slope_is_a_trapezoid_without_a_shelf():
    """Рамка 1,0 × 1,5 м под скатом 35° (верхние углы рамки — на 3,8 м, скат там 3,35 и 4,05 м):
    верх окна — отрезок параллельно скату через дальний верхний угол рамки, полки нет."""
    shape = _slope_outline(0.5, 2.3, 1.0, 1.5)
    left = 3.8 - TAN * 1.0  # верх у левого края: параллельно скату от угла (1,5; 3,8)
    assert _same(shape, [(0.5, 2.3), (1.5, 2.3), (1.5, 3.8), (0.5, left)]), shape
    top = [p for p in shape if p[1] > 3.0]  # верх: два угла выше карниза
    assert abs((top[0][1] - top[1][1]) / (top[0][0] - top[1][0])) - TAN < 0.01


def test_slope_window_under_the_ridge_is_a_pentagon_with_a_sharp_ridge():
    """Рамка 1,0 × 1,6 м у конька: оба ската сдвинуты до касания верха рамки по оси — острый
    конёк на верху рамки (4,6 м), боковые углы ниже на 0,5 · tg 35°."""
    shape = _slope_outline(2.5, 3.0, 1.0, 1.6)
    side = 4.6 - 0.5 * TAN
    want = [(2.5, 3.0), (3.5, 3.0), (3.5, side), (3.0, 4.6), (2.5, side)]
    assert _same(shape, want), shape


def test_slope_window_far_from_the_slope_stays_the_frame():
    """Рамка не ближе отступа к скату — прямоугольник, как прежде."""
    assert len(_slope_outline(0.5, 3.0, 1.0, 0.1)) == 4
