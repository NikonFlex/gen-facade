import re

import pytest

from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg
from genfacade.schema import ElementClass, OpeningVariant, VariantKind


def test_coordinates_survive_exactly(cfg, lay_out):
    # Круглые координаты округление в SVG не выдают — подставляем дробные.
    sheet = lay_out()
    w = sheet.facades[0].elements[1]
    w.x_m, w.w_m = 1 / 3, 2 / 3
    elements, _ = parse_sheet_svg(sheet_svg(sheet, cfg))[0]
    assert (elements[1].x_m, elements[1].w_m) == (1 / 3, 2 / 3)


def test_sheet_has_level_marks_and_axes(cfg, lay_out):
    # простой дом: земля, цоколь 0.5, карниз (он же верх стены при плоской крыше) 3.25
    svg = sheet_svg(lay_out(), cfg)
    for text in ("±0,000", "+0,500", "+3,250", "Фасад в осях 1–2", "Фасад в осях Б–А"):
        assert text in svg


def _door_sheet(sheet, kind):
    """Простой дом, у входной двери — вид kind."""
    door = next(e for e in sheet.facades[0].elements if e.cls is ElementClass.DOOR)
    door.variant = OpeningVariant(kind=kind, cols=1, rows=2)
    return door


@pytest.mark.parametrize("kind", [VariantKind.GLAZED, VariantKind.TRANSOM])
def test_door_glass_drawn_inside_door(cfg, lay_out, kind):
    """Стекло двери — в полотне или фрамугой сверху; разбор листа возвращает ту же дверь."""
    sheet = lay_out()
    door = _door_sheet(sheet, kind)
    svg = sheet_svg(sheet, cfg)
    [glass] = re.findall(r'<rect class="door-glass" x="([\d.]+)" y="([\d.]+)" '
                         r'width="([\d.]+)" height="([\d.]+)"', svg)
    x, y, w, h = map(float, glass)
    assert door.x_m <= x and x + w <= door.x_m + door.w_m
    assert door.y_m < y and y + h <= door.y_m + door.h_m + 1e-9
    # фрамуга — во всю ширину у самого верха; стекло в полотне — уже полотна и ниже верха
    at_top = y + h == pytest.approx(door.y_m + door.h_m)
    assert (at_top, w == pytest.approx(door.w_m)) == (kind is VariantKind.TRANSOM,) * 2
    parsed, _ = parse_sheet_svg(svg)[0]
    assert next(e for e in parsed if e.id == door.id).variant == door.variant


def test_solid_door_has_no_glass(cfg, lay_out):
    assert 'class="door-glass"' not in sheet_svg(lay_out(), cfg)
