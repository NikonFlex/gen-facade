"""Подсказка разметчику растрового листа (gf#328): на JPEG строим.дом.рф путей PDF нет, рамку окна
разметчик прикидывает глазами по кадру с линейкой (`grid`), а `snap` подтягивает края прикидки к
тёмным линиям рамки. Лист — PDF из картинок проекта, 1 pt = 1 px (`tools/fetch_stroim.py`).
"""

import numpy
import pdfplumber
from PIL import Image, ImageDraw, ImageFont

DARK = 110        # яркость пикселя линии чертежа, 0–255: темнее — линия
LINE_SHARE = 0.5  # строка или столбец — край рамки: доля тёмных пикселей вдоль края не меньше
STEP = 50         # pt: шаг линейки кадра
REACH = 15        # pt: насколько далеко от прикидки искать край


def page_image(pdf: str, page_no: int) -> Image.Image:
    """Страница листа в пикселях, 1 px = 1 pt."""
    with pdfplumber.open(pdf) as doc:
        page = doc.pages[page_no - 1]
        return page.to_image(resolution=72).original.convert("L")


def grid(pdf: str, page_no: int, box: tuple[float, ...], zoom: int) -> Image.Image:
    """Кадр листа с линейкой: подписи в pt через STEP, тонкая сетка через STEP / 5."""
    img = page_image(pdf, page_no)
    x0, y0, x1, y1 = (int(v) for v in box)
    crop = img.crop((x0, y0, x1, y1)).convert("RGB")
    crop = crop.resize((crop.width * zoom, crop.height * zoom), Image.NEAREST)
    d = ImageDraw.Draw(crop)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 12)
    except OSError:
        font = ImageFont.load_default()
    fine = STEP // 5
    for x in range(x0 - x0 % fine + fine, x1, fine):
        major = x % STEP == 0
        d.line([((x - x0) * zoom, 0), ((x - x0) * zoom, crop.height)],
               fill=(255, 0, 0) if major else (255, 190, 190), width=1)
        if major:
            d.text(((x - x0) * zoom + 2, 2), str(x), fill=(200, 0, 0), font=font)
    for y in range(y0 - y0 % fine + fine, y1, fine):
        major = y % STEP == 0
        d.line([(0, (y - y0) * zoom), (crop.width, (y - y0) * zoom)],
               fill=(0, 0, 255) if major else (190, 190, 255), width=1)
        if major:
            d.text((2, (y - y0) * zoom + 2), str(y), fill=(0, 0, 200), font=font)
    return crop


def snap(pdf: str, page_no: int, box: tuple[float, ...]) -> tuple[int, int, int, int]:
    """Прикидка рамки → края по самым внешним тёмным линиям в пределах REACH от неё; край без
    линии остаётся как был."""
    dark = numpy.asarray(page_image(pdf, page_no)) < DARK
    x0, y0, x1, y1 = (int(round(v)) for v in box)

    def column(x: int) -> float:
        return dark[y0:y1, x].mean() if 0 <= x < dark.shape[1] else 0.0

    def row(y: int) -> float:
        return dark[y, x0:x1].mean() if 0 <= y < dark.shape[0] else 0.0

    def first(candidates: range, share) -> int | None:
        return next((v for v in candidates if share(v) >= LINE_SHARE), None)

    left = first(range(x0 - REACH, x0 + REACH + 1), column)
    right = first(range(x1 + REACH, x1 - REACH - 1, -1), column)
    top = first(range(y0 - REACH, y0 + REACH + 1), row)
    bottom = first(range(y1 + REACH, y1 - REACH - 1, -1), row)
    return (x0 if left is None else left, y0 if top is None else top,
            x1 if right is None else right + 1, y1 if bottom is None else bottom + 1)
