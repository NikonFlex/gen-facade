from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg


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
