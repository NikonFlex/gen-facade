import math

import pytest

from genfacade.schema import Side
from genfacade.unfold import plan_corners, ridge_height, unfold


def test_gable_ridge_height(load_house):
    # Торец 8 м, уклон 35°, карниз 3.3 м: подъём = 4 · tg 35°.
    sheet = load_house("house_gable")
    ridge = ridge_height(sheet.spec, [f.side for f in sheet.facades])
    assert ridge == pytest.approx(3.3 + 4 * math.tan(math.radians(35)))


def test_gable_only_on_ends(load_house, cfg):
    sheet = unfold(load_house("house_gable"), cfg.library.roof.thickness_m)
    vertices = [len(f.silhouette) for f in sheet.facades]
    assert vertices == [4, 5, 4, 5]  # конёк вдоль x: фронтоны на западе и востоке


def test_hip_ridge_shorter_than_wall(load_house, cfg):
    sheet = unfold(load_house("house_hip"), cfg.library.roof.thickness_m)
    south = sheet.facades[0]
    ridge_xs = [x for x, y in south.roof if y == max(yy for _, yy in south.roof)]
    # Вальма под 45° в плане: конёк короче стены на глубину дома (9 м).
    assert max(ridge_xs) - min(ridge_xs) == pytest.approx(12 - 9)


def test_flat_roof_has_no_roof_outline(load_house, cfg):
    sheet = unfold(load_house("house_flat"), cfg.library.roof.thickness_m)
    assert all(f.roof is None for f in sheet.facades)


def test_corners_of_rectangle(load_house):
    sheet = load_house("house_gable")
    corners = plan_corners([f.side for f in sheet.facades])
    assert corners == [(0.0, 0.0), (-10.0, 0.0), (-10.0, 8.0), (0.0, 8.0)]


def test_counterclockwise_sides_rejected():
    sides = [
        Side(index=0, length_m=10, orientation=(0, -1)),
        Side(index=1, length_m=8, orientation=(1, 0)),  # по часовой после юга — запад
        Side(index=2, length_m=10, orientation=(0, 1)),
        Side(index=3, length_m=8, orientation=(-1, 0)),
    ]
    with pytest.raises(ValueError, match="по часовой"):
        plan_corners(sides)
