"""Критерии приёмки specs/facade.md, которые закрывает этап 0."""

import pytest

from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg
from genfacade.schema import FacadeSheet, Polygon
from genfacade.unfold import unfold


def _height_at(poly: Polygon, x: float) -> float:
    """Верх многоугольника над точкой x стены (для угла — x = 0 или длина)."""
    return max(py for px, py in poly if abs(px - x) < 1e-9)


def _with_ridge(house: FacadeSheet, axis: str) -> FacadeSheet:
    roof = house.spec.roof.model_copy(update={"ridge_axis": axis})
    return house.model_copy(update={"spec": house.spec.model_copy(update={"roof": roof})})


def _ridge_seen(f) -> float:
    """Конёк на виде стороны: у фронтона — вершина стены, иначе — верх крыши.

    Полоса ската над фронтоном выше конька на толщину кровли, её не считаем.
    """
    if len(f.silhouette) == 5:
        return max(y for _, y in f.silhouette)
    return max(y for _, y in (f.roof or f.silhouette))


@pytest.mark.parametrize("axis", ["x", "y"])
def test_corners_meet(house, axis):
    """На углах соседних фасадов совпадают отметки карниза и конька."""
    sheet = unfold(_with_ridge(house, axis))
    facades = sheet.facades
    for a, b in zip(facades, facades[1:] + facades[:1], strict=True):
        # Левый край a (x = 0) — угол i+1; у следующей стороны b это правый край (x = длина).
        corner_b = _height_at(b.silhouette, b.side.length_m)
        assert _height_at(a.silhouette, 0.0) == pytest.approx(corner_b)
    seen = [_ridge_seen(f) for f in facades]
    assert seen == pytest.approx([seen[0]] * len(seen)), "конёк с разных сторон на разной высоте"


def test_json_svg_json_roundtrip(house):
    """JSON → SVG → разбор SVG → JSON даёт тот же набор элементов."""
    sheet = unfold(house)
    parsed = parse_sheet_svg(sheet_svg(sheet))
    assert sorted(parsed) == [f.side.index for f in sheet.facades]
    for f in sheet.facades:
        elements, zones = parsed[f.side.index]
        assert elements == f.elements
        assert zones == f.zones


def test_svg_is_deterministic(house):
    """SVG получается из JSON детерминированно (facade.md, правило 7)."""
    sheet = unfold(house)
    assert sheet_svg(sheet) == sheet_svg(sheet.model_copy(deep=True))
