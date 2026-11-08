"""Рисунок выводимых элементов на листе (gf#318): ставни, козырёк, сандрик наличника, полотно
двери. Что рисовать, решает форма (`shape`) записи вида в config/derive.toml, размеры рисунка —
config/sheet.toml, [trim] и запись; вид дома выбирает запись, модель шага 4 его не знает.
Прямоугольник элемента (derive.py) — рамка рисунка: рисунок не выходит за неё.
"""

import math
from xml.etree import ElementTree

from genfacade.config import CanopyLook, CasingLook, DoorLeaf, ShutterLook, TrimLook
from genfacade.render.shapes import add_line, box, points
from genfacade.schema import CanopyShape, CasingShape, DoorShape, Element, Point, ShutterShape

DOME_STEPS = 16  # звеньев дуги арки и сегмента: глазу достаточно, в разбор рисунок не входит


def casing_framed(shape: CasingShape) -> bool:
    """Наличник со своим контуром (сандрик): прямоугольник элемента — только рамка для разбора."""
    return shape is not CasingShape.FRAME


def canopy_framed(shape: CanopyShape) -> bool:
    return shape is not CanopyShape.SLAB


def casing(g: ElementTree.Element, e: Element, look: CasingLook) -> ElementTree.Element:
    """Контур наличника с сандриком: рамка по бокам и сверху, над ней — треугольник или дуга."""
    top = e.y_m + e.h_m - look.rise_m
    x0, x1 = e.x_m, e.x_m + e.w_m
    if look.shape is CasingShape.PEDIMENT:
        roof = [((x0 + x1) / 2, top + look.rise_m)]
    else:
        roof = list(reversed(_dome(x0, x1, top, look.rise_m)))
    shape = [(x0, e.y_m), (x1, e.y_m), (x1, top), *roof, (x0, top)]
    return ElementTree.SubElement(g, "polygon", {"points": points(shape)})


def _dome(x0: float, x1: float, y: float, rise: float) -> list[Point]:
    """Дуга над основанием x0…x1 на высоте y: полуэллипс высотой rise, слева направо."""
    mid, half = (x0 + x1) / 2, (x1 - x0) / 2
    angles = [math.pi * (1 - k / DOME_STEPS) for k in range(1, DOME_STEPS)]
    return [(mid + half * math.cos(a), y + rise * math.sin(a)) for a in angles]


def shutter(g: ElementTree.Element, e: Element, look: ShutterLook | None, p: TrimLook) -> None:
    """Рисунок створки: планки жалюзи, доски, две филёнки или доски на планках с диагональю; вида
    у дома нет (look — None) — ставня остаётся прямоугольником."""
    if look is None:
        return
    x0, y0, w, h = e.x_m, e.y_m, e.w_m, e.h_m
    if look.shape is ShutterShape.LOUVER:
        for k in range(1, int(h / p.louver_step_m)):
            y = y0 + k * p.louver_step_m
            add_line(g, "trim-line", (x0, y), (x0 + w, y))
    elif look.shape in (ShutterShape.BOARD, ShutterShape.BATTEN_Z):
        for k in range(1, int(w / p.board_step_m)):
            x = x0 + k * p.board_step_m
            add_line(g, "trim-line", (x, y0), (x, y0 + h))
    if look.shape is ShutterShape.PANEL:
        _panels(g, (x0, y0, w, h), 1, 2, p.panel_inset)
    elif look.shape is ShutterShape.BATTEN_Z:
        low, high = y0 + h * p.batten_at, y0 + h * (1 - p.batten_at)
        for y in (low, high):
            add_line(g, "trim-line", (x0, y), (x0 + w, y))
        add_line(g, "trim-line", (x0, low), (x0 + w, high))


def _panels(g: ElementTree.Element, rect: tuple[float, ...], cols: int, rows: int,
            inset: float) -> None:
    """Сетка филёнок cols × rows в рамке; отступ inset — доля ширины рамки, со всех сторон один."""
    x0, y0, w, h = rect
    gap = w * inset
    pw, ph = (w - (cols + 1) * gap) / cols, (h - (rows + 1) * gap) / rows
    for i in range(cols):
        for j in range(rows):
            box(g, "trim-line", (x0 + gap + i * (pw + gap), y0 + gap + j * (ph + gap), pw, ph)
                ).set("fill", "none")


def canopy(g: ElementTree.Element, e: Element, look: CanopyLook, p: TrimLook,
           foot: float) -> ElementTree.Element:
    """Козырёк: двускатный — треугольник, арочный — свод, на кронштейнах — плита и два кронштейна,
    на столбах — плита и два столба вниз до foot, низа двери."""
    x0, y0, w, h = e.x_m, e.y_m, e.w_m, e.h_m
    if look.shape is CanopyShape.GABLE:
        shape = [(x0, y0), (x0 + w, y0), (x0 + w / 2, y0 + h)]
    elif look.shape is CanopyShape.ARCHED:
        shape = [(x0, y0), (x0 + w, y0), *reversed(_dome(x0, x0 + w, y0, h))]
    else:
        return _slab_on_supports(g, e, look, p, foot)
    return ElementTree.SubElement(g, "polygon", {"points": points(shape)})


def _slab_on_supports(g: ElementTree.Element, e: Element, look: CanopyLook, p: TrimLook,
                      foot: float) -> ElementTree.Element:
    """Плита сверху и две опоры: кронштейны-треугольники под плитой или столбы до foot."""
    x0, y0, w, h = e.x_m, e.y_m, e.w_m, e.h_m
    slab = min(p.slab_m, h)
    top = ElementTree.SubElement(g, "g")
    box(top, "", (x0, y0 + h - slab, w, slab))
    if look.shape is CanopyShape.POSTS:
        for x in (x0, x0 + w - p.post_w_m):
            box(top, "", (x, foot, p.post_w_m, y0 + h - slab - foot))
        return top
    for at, side in ((x0 + w * p.bracket_at, 1), (x0 + w * (1 - p.bracket_at), -1)):
        shape = [(at, y0 + h - slab), (at, y0), (at + side * p.bracket_w_m, y0 + h - slab)]
        ElementTree.SubElement(top, "polygon", {"points": points(shape)})
    return top


def leaf_box(e: Element, leaf: DoorLeaf) -> tuple[float, float, float, float]:
    """Полотно двери: проём, а при боковых стёклах — без полос по краям."""
    side = e.w_m * leaf.side_share
    return (e.x_m + side, e.y_m, e.w_m - 2 * side, e.h_m)


def door(g: ElementTree.Element, e: Element, leaf: DoorLeaf, glass: str) -> None:
    """Рисунок полотна под стеклом: филёнки, шов двупольной двери, боковые стёкла."""
    x, y, w, h = leaf_box(e, leaf)
    if leaf.shape is DoorShape.PANELS:
        _panels(g, (x, y, w, h), leaf.cols, leaf.rows, leaf.inset)
    elif leaf.shape is DoorShape.DOUBLE:
        _panels(g, (x, y, w, h), 2, leaf.rows, leaf.inset)
        add_line(g, "trim-line", (x + w / 2, y), (x + w / 2, y + h))
    elif leaf.shape is DoorShape.SIDELIGHTS:
        side = e.w_m * leaf.side_share
        for sx in (e.x_m, e.x_m + e.w_m - side):
            box(g, "door-glass", (sx, y, side, h)).set("fill", glass)
