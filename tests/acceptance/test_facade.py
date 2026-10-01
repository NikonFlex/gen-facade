"""Критерии приёмки specs/facade.md, которые закрывает этап 0."""

import pytest

from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg
from genfacade.schema import EPS, Polygon


def _height_at(poly: Polygon, x: float) -> float:
    """Верх многоугольника над точкой x стены (для угла — x = 0 или длина)."""
    return max(py for px, py in poly if abs(px - x) < EPS)


def test_corners_meet(house):
    """На углах соседних фасадов совпадают отметки верха стены."""
    facades = house.facades
    for a, b in zip(facades, facades[1:] + facades[:1], strict=True):
        # Левый край a (x = 0) — угол i+1; у следующей стороны b это правый край (x = длина).
        corner_b = _height_at(b.silhouette, b.side.length_m)
        assert _height_at(a.silhouette, 0.0) == pytest.approx(corner_b)


def test_json_svg_json_roundtrip(house, cfg):
    """JSON → SVG → разбор SVG → JSON даёт тот же набор элементов."""
    sheet = house
    parsed = parse_sheet_svg(sheet_svg(sheet, cfg))
    assert sorted(parsed) == [f.side.index for f in sheet.facades]
    for f in sheet.facades:
        elements, zones = parsed[f.side.index]
        assert elements == f.elements
        assert zones == f.zones


def test_svg_is_deterministic(house, cfg):
    """SVG получается из JSON детерминированно (facade.md, правило 7)."""
    sheet = house
    assert sheet_svg(sheet, cfg) == sheet_svg(sheet.model_copy(deep=True), cfg)
