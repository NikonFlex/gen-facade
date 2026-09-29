from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg
from genfacade.unfold import unfold


def test_coordinates_survive_exactly(load_house):
    # В тестовых домах координаты круглые — округление в SVG на них не видно.
    sheet = unfold(load_house("house_gable"))
    w = sheet.facades[0].elements[1]
    w.x_m, w.w_m = 1 / 3, 2 / 3
    elements, _ = parse_sheet_svg(sheet_svg(sheet))[0]
    assert (elements[1].x_m, elements[1].w_m) == (1 / 3, 2 / 3)


def test_sheet_has_level_marks_and_axes(load_house):
    svg = sheet_svg(unfold(load_house("house_gable")))
    for text in ("±0,000", "+0,500", "+3,300", "+6,101", "Фасад в осях 1–2", "Фасад в осях Б–А"):
        assert text in svg
