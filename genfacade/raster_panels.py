"""Картинка стены для глаз хозяина (gf#17): три панели рядом — вход векторизатора, отрисовка его SVG
как есть и найденные элементы рамками поверх неё. Подписи латиницей: шрифт PIL по умолчанию без
кириллицы."""

import numpy
from PIL import Image, ImageDraw, ImageFont

from genfacade.raster_read import Region

TITLES = ("input raster", "vectorizer SVG as drawn", "elements found (visible)")
GAP_PX = 8
HEADER_PX = 18
FONT = "DejaVuSans.ttf"
FONT_PX = 11
BACKGROUND = (255, 255, 255)
INK = (0, 0, 0)
OUTLINE = ((INK, 2), (BACKGROUND, 1))  # чёрная рамка с белой серединой видна на любом цвете


def font() -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT, FONT_PX)
    except OSError:
        return ImageFont.load_default()


def mark(image: Image.Image, found: list[Region]) -> Image.Image:
    """Копия картинки с рамками областей и подписью класса у верхнего левого угла."""
    out, label = image.copy(), font()
    pen = ImageDraw.Draw(out)
    for region in found:
        x0, y0, x1, y1 = region.box
        for color, width in OUTLINE:
            pen.rectangle((x0, y0, x1 - 1, y1 - 1), outline=color, width=width)
        pen.text((x0 + 2, y0 + 2), region.cls.value, fill=INK, font=label)
    return out


def draw(raster: numpy.ndarray, rendered: numpy.ndarray, found: list[Region]) -> Image.Image:
    """Вход | отрисовка SVG | отрисовка с найденными рамками."""
    height, width = raster.shape[:2]
    panels = (Image.fromarray(raster), Image.fromarray(rendered),
              mark(Image.fromarray(rendered), found))
    sheet = Image.new("RGB", (3 * width + 2 * GAP_PX, height + HEADER_PX), BACKGROUND)
    pen, label = ImageDraw.Draw(sheet), font()
    for k, (title, panel) in enumerate(zip(TITLES, panels, strict=True)):
        left = k * (width + GAP_PX)
        pen.text((left + 2, 2), title, fill=INK, font=label)
        sheet.paste(panel, (left, HEADER_PX))
    return sheet
