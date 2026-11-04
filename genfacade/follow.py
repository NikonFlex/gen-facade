"""Шаг 5: выводимые элементы едут за своим проёмом (gf#212).

Подоконник, наличник, ставни и козырёк ставит derive.py по проёму; когда привязка (snap.py) или
выравнивание уровней (levels.py) двигает проём, его дети повторяют сдвиг и растяжение.
"""

from genfacade.schema import EPS, Element


def follow(child: Element, moved: dict[str, Element], before: list[Element]) -> Element:
    """Ребёнок проёма повторяет сдвиг и растяжение своего проёма; проём не двигался — как был."""
    if child.parent not in moved:
        return child
    old = next(e for e in before if e.id == child.parent)
    new = moved[child.parent]
    if box(old) == box(new):  # проём не сдвинулся — хвосты float не трогают точные числа
        return child
    x, w = _follow_x(child, old, new)
    y, h = _follow_y(child, old, new)
    return child.model_copy(update={"x_m": x, "w_m": w, "y_m": y, "h_m": h})


def _follow_x(child: Element, old: Element, new: Element) -> tuple[float, float]:
    """Сбоку от проёма (ставня) — тот же зазор до его края, ширина — в долю проёма; над, под
    проёмом и вокруг него — тянется с ним. Проём сузился больше ширины элемента (окно плана
    уже окна модели, gf#257: крыльцо у сайдлайта шириной 0,37 м) — элемент тоже в долю проёма,
    иначе ширина уходит в минус."""
    k = new.w_m / old.w_m
    if child.x_m + child.w_m <= old.x_m + EPS:
        w = child.w_m * k
        return new.x_m - (old.x_m - child.x_m - child.w_m) - w, w
    if child.x_m >= old.x_m + old.w_m - EPS:
        w = child.w_m * k
        return new.x_m + new.w_m + (child.x_m - old.x_m - old.w_m), w
    if child.w_m + new.w_m - old.w_m > EPS:
        return child.x_m + (new.x_m - old.x_m), child.w_m + (new.w_m - old.w_m)
    return new.x_m + (child.x_m - old.x_m) * k, child.w_m * k


def box(e: Element) -> tuple[float, float, float, float]:
    """Прямоугольник элемента: x, y, ширина, высота."""
    return e.x_m, e.y_m, e.w_m, e.h_m


def _follow_y(child: Element, old: Element, new: Element) -> tuple[float, float]:
    """Под проёмом (подоконник) — едет с низом, над ним (козырёк) — с верхом, рядом и вокруг
    (ставни, наличник) — тянется с проёмом."""
    dy, dh = new.y_m - old.y_m, new.h_m - old.h_m
    if child.y_m + child.h_m <= old.y_m + EPS:
        return child.y_m + dy, child.h_m
    if child.y_m >= old.y_m + old.h_m - EPS:
        return child.y_m + dy + dh, child.h_m
    return child.y_m + dy, child.h_m + dh
