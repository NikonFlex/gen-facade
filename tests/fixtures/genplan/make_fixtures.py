"""Пересобрать тестовые SVG кодом GenPlan: двери рисует его decorator, как в настоящем плане.

    python make_fixtures.py <клон GenPlan> <папка для SVG>

Нужны клон https://github.com/CTLab-ITMO/GenPlan (сверено на HEAD 2ed651c) и `pip install drawsvg`.
Геометрия — наша; GenPlan только рисует. Положения створки: door_top — BOTTOM,
door_left — RIGHT, door_edge — UP и LEFT (у края холста снаружи места нет).
house — дом с теми же особенностями, что пример GenPlan (materials/, в git не лежит — gf#20):
вход со створкой на левой стене, окна на верхней и левой, внутренняя стена заходит в полосу
верхнего окна (дефект GenPlan), внутренние стены прорисованы насквозь до наружной грани.
Окна и двери расставляет decorator GenPlan (create_windows_and_doors_2d).
"""

import sys
from pathlib import Path

CANVAS = 600
GAP_SIDES = ("top", "left")


def main(genplan: Path, out: Path) -> None:
    sys.path.insert(0, str(genplan))
    # модули GenPlan и drawsvg есть только рядом с клоном — импорт после sys.path
    import drawsvg
    from decorator.decoration import create_opened_doors, create_windows_and_doors_2d
    from dto.enum.rect_type import RectType
    from dto.point import Point
    from dto.rect import Rect

    def rect(x0, y0, x1, y1):
        return Rect(Point(x0, y0), Point(x1, y1), [0, 0, 0], RectType.WALL)

    def save(name, walls, openings):
        pic = drawsvg.Drawing(CANVAS, CANVAS)
        for r in walls + create_opened_doors(walls, openings, CANVAS, CANVAS):
            r.to_svg(pic)
        pic.save_svg(str(out / f"{name}.svg"))

    for side in GAP_SIDES:
        walls, opening = _box(rect, lo=100, hi=500, gap_side=side)
        save(f"door_{side}", walls, [opening])
    # коробка у угла холста: створкам наружу не встать — GenPlan ставит их внутрь
    walls, top = _box(rect, lo=0, hi=400, gap_side="top")
    left = rect(0, 150, 15, 240)
    walls = [w for w in walls if not (w.start_point.x == 0 and w.end_point.x == 15)]
    walls += [rect(0, 0, 15, 150), rect(0, 240, 15, 400)]
    save("door_edge", walls, [top, left])
    walls = _house(rect)
    pic = drawsvg.Drawing(CANVAS, CANVAS)
    for r in walls + create_windows_and_doors_2d(walls, CANVAS, CANVAS):
        r.to_svg(pic)
    pic.save_svg(str(out / "house.svg"))


def _house(rect):
    """Коробка 100..500 × 150..450, стены 15 px; разрывы: вход 90 px и окно 100 px слева,
    окно 150 px сверху; внутренние стены — одна заходит в полосу верхнего окна."""
    return [
        rect(100, 150, 250, 165), rect(400, 150, 500, 165),  # верх, окно 250–400
        rect(100, 150, 115, 200), rect(100, 290, 115, 330), rect(100, 420, 115, 450),  # лево
        rect(485, 150, 500, 450), rect(100, 435, 500, 450),  # право, низ
        rect(330, 158, 339, 300),  # в полосу окна сверху: 158 > 150 — не насквозь
        rect(100, 310, 250, 320),  # от наружной грани слева — насквозь
        rect(300, 350, 310, 450),  # до наружной грани снизу — насквозь
    ]


def _box(rect, lo: int, hi: int, gap_side: str):
    """Коробка lo..hi, стены 15 px; на стороне `gap_side` разрыв 90 px, начиная с lo + 150."""
    t, a, b = 15, lo + 150, lo + 240
    if gap_side == "top":
        walls = [rect(lo, lo, a, lo + t), rect(b, lo, hi, lo + t), rect(lo, lo, lo + t, hi)]
        opening = rect(a, lo, b, lo + t)
    else:
        walls = [rect(lo, lo, hi, lo + t), rect(lo, lo, lo + t, a), rect(lo, b, lo + t, hi)]
        opening = rect(lo, a, lo + t, b)
    walls += [rect(lo, hi - t, hi, hi), rect(hi - t, lo, hi, hi)]
    return walls, opening


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
