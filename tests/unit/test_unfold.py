import math

import pytest

from genfacade.schema import Side, top_y
from genfacade.unfold import plan_corners, ridge_height


def test_gable_ridge_height(lay_out):
    # Простой дом: торец 5 м, уклон 30°, карниз 3.25 м — подъём 2.5 · tg 30°.
    sheet = lay_out(roof="gable")
    ridge = ridge_height(sheet.spec, [f.side for f in sheet.facades])
    assert ridge == pytest.approx(3.25 + 2.5 * math.tan(math.radians(30)))


def test_gable_only_on_ends(lay_out):
    sheet = lay_out(roof="gable")
    vertices = [len(f.silhouette) for f in sheet.facades]
    assert vertices == [4, 5, 4, 5]  # конёк вдоль длинной стороны (x): фронтоны на торцах


def test_hip_ridge_shorter_than_wall(lay_out):
    sheet = lay_out(roof="hip")
    long_side = sheet.facades[0]
    ridge_xs = [x for x, y in long_side.roof if y == top_y(long_side.roof)]
    # Вальма под 45° в плане: конёк короче стены на глубину дома (5 м).
    assert max(ridge_xs) - min(ridge_xs) == pytest.approx(10 - 5)


def test_flat_roof_has_no_roof_outline(lay_out):
    assert all(f.roof is None for f in lay_out().facades)


def test_corners_of_rectangle(lay_out):
    sheet = lay_out()
    corners = plan_corners([f.side for f in sheet.facades])
    assert corners == pytest.approx([(0.0, 0.0), (-10.0, 0.0), (-10.0, 5.0), (0.0, 5.0)])


def test_counterclockwise_sides_rejected():
    sides = [
        Side(index=0, length_m=10, orientation=(0, -1)),
        Side(index=1, length_m=8, orientation=(1, 0)),  # по часовой после юга — запад
        Side(index=2, length_m=10, orientation=(0, 1)),
        Side(index=3, length_m=8, orientation=(-1, 0)),
    ]
    with pytest.raises(ValueError, match="по часовой"):
        plan_corners(sides)
