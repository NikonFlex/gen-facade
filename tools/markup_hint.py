"""Подсказка разметчику (gf#180): что лежит на листе фасада в кадре — длинные осевые линии (края
стены, уровни, балки) и рамки путей (окна, двери, ставни) в pt листа и в дюймах. Запуск —
`python tools/markup.py hint`.

Координаты — как у pdfplumber: x вправо, y (top) вниз, pt. Окна и двери на листах FreeFarmhouse —
незамкнутые ломаные, а не `rect`: рамку элемента разметчик собирает из этих путей глазами.
"""

import pdfplumber

FLAT = 0.3       # pt: отрезок с таким разбросом по одной оси — осевой
SHORT = 3.0      # pt: короче — штриховка и засечки, не линия
LONG_V_FT, LONG_H_FT, MAX_PATH_FT = 3, 6, 20  # что печатать: в футах листа


def segments(page, box: tuple[float, ...]) -> list[tuple[str, float, float, float]]:
    """Осевые отрезки в кадре: (вид v|h, начало, конец, положение по другой оси)."""
    x0, y0, x1, y1 = box
    out = []
    for o in page.lines + page.curves + page.rects:
        pts = o.get("pts") or []
        if o["object_type"] == "rect":
            pts = [(o["x0"], o["top"]), (o["x1"], o["top"]), (o["x1"], o["bottom"]),
                   (o["x0"], o["bottom"]), (o["x0"], o["top"])]
        for (ax, ay), (bx, by) in zip(pts, pts[1:], strict=False):
            if not (x0 <= min(ax, bx) and max(ax, bx) <= x1 and y0 <= min(ay, by)
                    and max(ay, by) <= y1):
                continue
            if abs(ay - by) < FLAT and abs(ax - bx) > SHORT:
                out.append(("h", min(ax, bx), max(ax, bx), (ay + by) / 2))
            elif abs(ax - bx) < FLAT and abs(ay - by) > SHORT:
                out.append(("v", min(ay, by), max(ay, by), (ax + bx) / 2))
    return out


def long_lines(segs: list, kind: str, min_pt: float) -> list[tuple]:
    return sorted({(round(s[3], 1), round(s[1]), round(s[2])) for s in segs
                   if s[0] == kind and s[2] - s[1] > min_pt})


def paths(page, box: tuple[float, ...], ft: float) -> list[str]:
    x0, y0, x1, y1 = box
    out = []
    for o in page.curves + page.rects:
        w, h = o["x1"] - o["x0"], o["bottom"] - o["top"]
        if (o["x0"] >= x0 and o["x1"] <= x1 and o["top"] >= y0 and o["bottom"] <= y1
                and ft < w < MAX_PATH_FT * ft and h > ft):
            out.append(f"path x0={o['x0']:.1f} top={o['top']:.1f} x1={o['x1']:.1f} "
                       f"bot={o['bottom']:.1f}  {w / ft * 12:.1f}x{h / ft * 12:.1f} in")
    return out


def hint(pdf: str, page_no: int, box: tuple[float, ...], ft: float) -> str:
    with pdfplumber.open(pdf) as doc:
        page = doc.pages[page_no - 1]
        segs = segments(page, box)
        lines = [f"long v: {long_lines(segs, 'v', LONG_V_FT * ft)}",
                 f"long h: {long_lines(segs, 'h', LONG_H_FT * ft)}"]
        return "\n".join(lines + paths(page, box, ft))
