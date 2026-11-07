"""Нарисовать непрямоугольные дома в формате GenPlan (gf#306) — без клона GenPlan и drawsvg.

    python make_nonrect_houses.py <папка для SVG>

Формат — тот же, что у `make_simple_house.py` и `simple_house.svg`: 1 px = 1 см, стены чёрные
`<rect>` толщиной 15 px по контуру внутрь, окно — разрыв в стене, залитый `#99ccff`, вход —
разрыв с дверной створкой (`<rect>` 5 px) и четвертью дуги. Контур — ортогональный многоугольник
(вершины по часовой стрелке на экране), проёмы заданы по рёбрам: (отступ от начала ребра в см,
ширина в см, вид). Окна противоположных стен разной ширины и не друг напротив друга: иначе
decorator GenPlan нарисовал бы ложное окно поперёк дома (gf#36).
"""

import sys
from dataclasses import dataclass
from pathlib import Path

WALL_PX = 15
LEAF_PX = 5
ORIGIN = (100, 100)
MARGIN = 100


@dataclass(frozen=True)
class Opening:
    offset: int  # от начала ребра, см
    width: int
    door: bool = False


@dataclass(frozen=True)
class House:
    name: str
    ring: list[tuple[int, int]]  # вершины по часовой стрелке (y вниз), см от угла
    openings: dict[int, list[Opening]]  # номер ребра → проёмы


def _w(offset: int, width: int) -> Opening:
    return Opening(offset, width)


def _d(offset: int) -> Opening:
    return Opening(offset, 90, door=True)


L_A = [(0, 0), (600, 0), (600, 350), (1000, 350), (1000, 800), (0, 800)]
L_A_BACK = {3: [_w(60, 150), _w(280, 110)], 5: [_w(130, 120), _w(400, 180), _w(640, 100)]}
BAY = {  # проёмы дома с эркером по низу: стороны 3 и 5 — бока эркера, глухие
    0: [_w(100, 160), _w(450, 220), _w(800, 100)],
    1: [_w(120, 150), _w(380, 120)],
    2: [_d(100)],
    4: [_w(50, 200)],
    6: [_w(60, 130)],
    7: [_w(100, 140), _w(300, 110)],
}

HOUSES = [
    # Г: вырезан правый верхний угол 400 × 350
    House("l-shape-a", L_A, L_A_BACK | {
        0: [_w(100, 200), _w(400, 120)],
        1: [_w(120, 100)],
        2: [_w(150, 150)],
        4: [_w(120, 150), _d(420), _w(580, 200)],  # обход справа налево
    }),
    # Г с окнами у самых углов: по 30 см до внутреннего угла с обеих сторон, 25 см до внешнего
    House("l-shape-corner", L_A, L_A_BACK | {
        0: [_w(100, 200), _w(375, 200)],
        1: [_w(220, 100)],
        2: [_w(30, 150), _w(250, 120)],
        4: [_w(120, 150), _d(420), _w(580, 195)],
    }),
    # Г: вырезан левый нижний угол 300 × 250, вход на выступающей ноге
    House("l-shape-b", [(0, 0), (900, 0), (900, 700), (300, 700), (300, 450), (0, 450)], {
        0: [_w(80, 150), _w(380, 220), _w(700, 100)],
        1: [_w(90, 120), _w(380, 160)],
        2: [_w(100, 180), _d(400)],
        3: [_w(80, 100)],
        4: [_w(100, 130)],
        5: [_w(100, 130), _w(300, 100)],
    }),
    # Т: перекладина 1200 × 400, ножка 500 × 400 внизу посередине
    House("t-shape", [(0, 0), (1200, 0), (1200, 400), (850, 400), (850, 800), (350, 800),
                      (350, 400), (0, 400)], {
        0: [_w(150, 200), _w(500, 120), _w(850, 160)],
        1: [_w(130, 140)],
        2: [_w(100, 110)],
        3: [_w(120, 120), _w(300, 100)],
        4: [_d(100), _w(260, 150)],
        5: [_w(90, 130), _w(270, 100)],
        6: [_w(100, 100)],
        7: [_w(120, 140)],
    }),
    # П: двор 400 × 400 открыт кверху между двумя крыльями по 400
    House("u-shape", [(0, 0), (400, 0), (400, 400), (800, 400), (800, 0), (1200, 0), (1200, 700),
                      (0, 700)], {
        0: [_w(130, 140)],
        1: [_w(120, 110)],
        2: [_w(110, 180)],
        3: [_w(200, 100)],
        4: [_w(140, 130)],
        5: [_w(140, 120), _w(300, 150)],
        6: [_w(150, 150), _d(400), _w(620, 200), _w(930, 100)],
        7: [_w(120, 130), _w(340, 190)],
    }),
    # Прямоугольник с пристройкой 350 × 300 справа, не вровень с углами
    House("annex", [(0, 0), (900, 0), (900, 150), (1250, 150), (1250, 450), (900, 450), (900, 600),
                    (0, 600)], {
        0: [_w(120, 200), _w(500, 150)],
        1: [_w(40, 100)],
        2: [_w(60, 180)],
        3: [_w(40, 100), _d(190)],
        4: [_w(110, 110)],
        5: [_w(30, 100)],
        6: [_w(400, 200), _w(90, 120)],
        7: [_w(140, 160), _w(390, 100)],
    }),
    # Прямоугольник с эркером 300 × 120 по низу (эркер глубже 0,6 м — часть контура)
    House("bay-120", [(0, 0), (1000, 0), (1000, 600), (650, 600), (650, 720), (350, 720),
                      (350, 600), (0, 600)], BAY),
    # Эркер 300 × 50: мельче 0,6 м — по правилам gf#199 элемент на стене, не контур
    House("bay-50", [(0, 0), (1000, 0), (1000, 600), (650, 600), (650, 650), (350, 650),
                     (350, 600), (0, 600)], BAY),
    # Г для двухэтажного дома: нога вниз слева
    House("l-shape-2fl", [(0, 0), (1100, 0), (1100, 400), (500, 400), (500, 800), (0, 800)], {
        0: [_w(120, 200), _w(450, 130), _w(780, 170)],
        1: [_w(100, 120), _w(260, 100)],
        2: [_w(100, 160), _w(350, 100)],
        3: [_w(60, 140), _w(250, 110)],
        4: [_d(100), _w(260, 120)],
        5: [_w(110, 150), _w(350, 100), _w(550, 130)],
    }),
]


def _unit(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    return (b[0] > a[0]) - (b[0] < a[0]), (b[1] > a[1]) - (b[1] < a[1])


def _rect(x0: float, y0: float, x1: float, y1: float, fill: str) -> str:
    x0, x1, y0, y1 = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    return (f'<rect x="{x0:g}" y="{y0:g}" width="{x1 - x0:g}" height="{y1 - y0:g}" '
            f'fill="{fill}" />')


def _is_reflex(ring: list[tuple[int, int]], i: int) -> bool:
    """Вершина i — внутренний угол (поворот налево при обходе по часовой стрелке на экране)."""
    a, b, c = ring[i - 1], ring[i], ring[(i + 1) % len(ring)]
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) < 0


def draw(house: House) -> str:
    """SVG плана дома: стены кусками между проёмами, окна, вход."""
    ring = [(x + ORIGIN[0], y + ORIGIN[1]) for x, y in house.ring]
    width = max(x for x, _ in ring) + MARGIN
    height = max(y for _, y in ring) + MARGIN
    body: list[str] = []
    n = len(ring)
    for i in range(n):
        a, b = ring[i], ring[(i + 1) % n]
        d = _unit(a, b)
        inward = (-d[1], d[0])  # внутрь дома — вправо от хода по часовой стрелке на экране
        length = abs(b[0] - a[0]) + abs(b[1] - a[1])
        # куски стены от начала до конца ребра, у внутреннего угла — ещё на толщину вперёд
        lo = -WALL_PX if _is_reflex(ring, i) else 0
        hi = length + (WALL_PX if _is_reflex(ring, (i + 1) % n) else 0)
        gaps = sorted(house.openings.get(i, []), key=lambda o: o.offset)
        cuts, pos = [], lo
        for g in gaps:
            cuts.append((pos, g.offset))
            pos = g.offset + g.width
        cuts.append((pos, hi))

        def box(t0, t1, a=a, d=d, inward=inward):
            return (a[0] + d[0] * t0, a[1] + d[1] * t0,
                    a[0] + d[0] * t1 + inward[0] * WALL_PX, a[1] + d[1] * t1 + inward[1] * WALL_PX)

        body += [_rect(*box(t0, t1), "#000000") for t0, t1 in cuts if t1 > t0]
        body += [_rect(*box(g.offset, g.offset + g.width), "#99ccff") for g in gaps if not g.door]
    # створки и дуги — после стен, как в simple_house.svg
    for i in range(n):
        a = ring[i]
        d = _unit(a, ring[(i + 1) % n])
        inward = (-d[1], d[0])
        for g in (g for g in house.openings.get(i, []) if g.door):
            hinge = (a[0] + d[0] * g.offset + inward[0] * WALL_PX,
                     a[1] + d[1] * g.offset + inward[1] * WALL_PX)
            jamb = (hinge[0] + d[0] * g.width, hinge[1] + d[1] * g.width)
            tip = (hinge[0] + inward[0] * g.width, hinge[1] + inward[1] * g.width)
            body.append(_rect(hinge[0], hinge[1], tip[0] + d[0] * LEAF_PX, tip[1] + d[1] * LEAF_PX,
                              "#000000"))
            body.append(f'<path d="M{jamb[0]:.1f},{jamb[1]:.1f} A{g.width},{g.width},0,0,0,'
                        f'{tip[0]:.1f},{tip[1]:.1f}" stroke="#000000" fill="none" '
                        'stroke-width="5" />')
    head = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"\n'
            f'     width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
            '<defs>\n</defs>\n')
    return head + "\n".join(body) + "\n</svg>\n"


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for house in HOUSES:
        (out / f"{house.name}.svg").write_text(draw(house), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
