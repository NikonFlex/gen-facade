"""ResPlan → стороны с проёмами (`data: Стены с проёмами из ResPlan`, gf#215).

План — в формате выпуска ResPlan: словарь слоёв shapely в пикселях, ось y вниз, площадь
листинга в м². Дом 200 × 120 px при площади 60 м² — 0,05 м на пиксель, 10 × 6 м.
"""

import pickle
from collections import OrderedDict

import pytest
from shapely import affinity, box, union_all

from genfacade import config
from genfacade.datasets.resplan import build, check, convert, dedup, load
from genfacade.schema import OpeningKind, Split

CFG = config.load()
RULES = CFG.data.resplan
W, H, T = 200, 120, 4          # дом и толщина стен, px ResPlan
WINDOW = box(40, 0, 80, T)     # на верхней стене: 2–4 м от левого края, ширина 2 м
# Вход 1 м, а не 0,9 м GenPlan: масштаб по ширине входа дал бы дом 9 × 5,4 м вместо 10 × 6.
FRONT_DOOR = box(90, H - T, 110, H)


def resplan_plan(window=WINDOW, plan_id: int = 1) -> dict:
    bands = union_all([box(0, 0, W, T), box(0, H - T, W, H), box(0, 0, T, H), box(W - T, 0, W, H)])
    return {"id": plan_id, "area": 60.0, "wall_depth": float(T),
            "wall": bands.difference(union_all([window, FRONT_DOOR])),
            "window": window, "door": None, "front_door": FRONT_DOOR,
            "inner": box(T, T, W - T, H - T)}


def north_side(house: build.House):
    """Сторона, на которую смотрит верх картинки ResPlan: в плане (y вверх) — нормаль (0, 1)."""
    return next(s for s in house.plan.sides if s.orientation == (0.0, 1.0))


def test_scale_comes_from_the_listing_area():
    assert convert.m_per_px(resplan_plan()) == pytest.approx(0.05)


def test_known_window_lands_on_its_side():
    """Окно ResPlan → проём стороны: x и ширина до 5 см. Снаружи, с севера, восток слева:
    окно в 2–4 м от западного угла — в 6–8 м от левого края фасада."""
    house, _ = build.convert_house(resplan_plan(), Split.TRAIN, CFG)
    side = north_side(house)
    assert side.length_m == pytest.approx(10.0, abs=0.05)
    [opening] = side.openings
    assert opening.kind is OpeningKind.WINDOW
    assert opening.x_m == pytest.approx(6.0, abs=0.05)
    assert opening.width_m == pytest.approx(2.0, abs=0.05)


def test_front_door_is_the_entrance():
    house, _ = build.convert_house(resplan_plan(), Split.TRAIN, CFG)
    entrance = [o for s in house.plan.sides for o in s.openings if o.kind is OpeningKind.ENTRANCE]
    assert [round(o.width_m, 2) for o in entrance] == [1.0]


def test_check_against_source_finds_every_opening():
    plan = resplan_plan()
    house, drawing = build.convert_house(plan, Split.TRAIN, CFG)
    match = check.against_source(plan, drawing, house.plan, RULES)
    assert (match.on_contour, match.found, match.extracted) == (2, 2, 2)
    assert match.clean


def test_gap_without_resplan_opening_is_wall():
    """Разрыв стены, где у ResPlan нет ни окна, ни двери (устье выемки), — не проём."""
    plan = resplan_plan() | {"window": None}
    house, _ = build.convert_house(plan, Split.TRAIN, CFG)
    assert north_side(house).openings == []


def test_door_next_to_window_stays_two_openings():
    """Дверь встык с окном (у ResPlan бывает) — два проёма, а не один и не разрезанный."""
    plan = resplan_plan()
    door = box(80, 0, 104, T)  # 1,2 м — шире входа, иначе входом стала бы она
    plan["door"] = door
    plan["wall"] = plan["wall"].difference(door)
    house, _ = build.convert_house(plan, Split.TRAIN, CFG)
    kinds = sorted(o.kind for o in north_side(house).openings)
    assert kinds == sorted([OpeningKind.WINDOW, OpeningKind.DOOR])


def test_slanted_walls_are_refused():
    plan = resplan_plan()
    plan["wall"] = affinity.rotate(plan["wall"], 10, origin=(W / 2, H / 2))
    with pytest.raises(convert.PlanError, match="не ортогональный"):
        convert.svg(plan, CFG)


def test_mirrored_copy_is_a_duplicate():
    """Почти дубль — тот же план, отражённый (листинг опубликован повторно)."""
    plan = resplan_plan()
    mirrored = {k: affinity.scale(v, -1, 1, origin=(W / 2, H / 2)) if hasattr(v, "geom_type")
                else v for k, v in plan.items()} | {"id": 2}
    other = resplan_plan(plan_id=3) | {"area": 90.0}
    groups = dedup.clusters([plan, mirrored, other], RULES)
    assert sorted(map(sorted, groups)) == [[0, 1], [2]]


def test_pickle_with_foreign_objects_is_refused(tmp_path):
    """Пикл исполняет код при загрузке: чужой глобал — отказ до исполнения."""
    path = tmp_path / "ResPlan.pkl"
    path.write_bytes(pickle.dumps([OrderedDict(id=1)]))
    with pytest.raises(pickle.UnpicklingError, match="collections.OrderedDict"):
        load.plans(path)
