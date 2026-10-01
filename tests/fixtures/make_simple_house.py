"""Нарисовать простой дом кодом GenPlan: план в том же формате, что выдаёт GenPlan.

    python make_simple_house.py <клон GenPlan> <папка для SVG>

Нужны клон https://github.com/CTLab-ITMO/GenPlan (сверено на HEAD 2ed651c) и `pip install drawsvg`.
Геометрия — наша: прямоугольник 10 × 5 м (1 px = 1 см, стены 15 px), в каждой стене по окну
разной ширины — слева 1.0 м, справа 1.5, сверху 2.0, снизу 1.2 — и вход 0.9 м снизу. Окна
и дверь расставляет decorator GenPlan (create_windows_and_doors_2d): вход — самый узкий разрыв.
Разрывы стоят так, чтобы у противоположных стен не было кусков равной длины: иначе decorator
нарисует ложное окно поперёк дома (gf#36).
"""

import sys
from pathlib import Path

CANVAS_W, CANVAS_H = 1200, 700


def main(genplan: Path, out: Path) -> None:
    sys.path.insert(0, str(genplan))
    # модули GenPlan и drawsvg есть только рядом с клоном — импорт после sys.path
    import drawsvg
    from decorator.decoration import create_windows_and_doors_2d
    from dto.enum.rect_type import RectType
    from dto.point import Point
    from dto.rect import Rect

    def rect(x0, y0, x1, y1):
        return Rect(Point(x0, y0), Point(x1, y1), [0, 0, 0], RectType.WALL)

    walls = [
        rect(100, 100, 600, 115), rect(800, 100, 1100, 115),  # верх: окно 2.0 м
        # низ: окно 1.2 м, вход 0.9 м
        rect(100, 585, 250, 600), rect(370, 585, 800, 600), rect(890, 585, 1100, 600),
        rect(100, 100, 115, 350), rect(100, 450, 115, 600),  # лево: окно 1.0 м
        rect(1085, 100, 1100, 250), rect(1085, 400, 1100, 600),  # право: окно 1.5 м
    ]
    pic = drawsvg.Drawing(CANVAS_W, CANVAS_H)
    for r in walls + create_windows_and_doors_2d(walls, CANVAS_W, CANVAS_H):
        r.to_svg(pic)
    pic.save_svg(str(out / "simple_house.svg"))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
