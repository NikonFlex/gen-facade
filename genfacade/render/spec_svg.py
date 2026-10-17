"""Трасса шага 1 (01_spec.svg): параметры дома той же отрисовкой, что у листа.

Слева — образец стены до карниза: цоколь и стена цветами палитры, справа от него — отметки
уровней, те же, что на листе; правее — палитра: образец цвета и «id · вид». Оформление —
config/sheet.toml ([spec]) и config/sheet.css (.spec-*).
"""

from xml.etree import ElementTree

from genfacade.config import Config
from genfacade.render import sheet_format
from genfacade.render.sheet_format import num
from genfacade.render.svg import (
    add_line,
    add_text,
    canvas,
    level_mark,
    levels,
    palette_colors,
    points,
)
from genfacade.schema import HouseSpec, PaletteRole


def spec_svg(spec: HouseSpec, cfg: Config) -> str:
    look = cfg.sheet.spec
    colors = palette_colors(spec, cfg)
    height = max(spec.eaves_m, len(spec.materials) * look.line_m) + 2 * look.margin_m
    width = _palette_x(cfg) + look.swatch_m + look.text_dx_m + look.text_w_m + look.margin_m
    root = canvas(width, height, cfg.css)
    _wall(root, spec, colors, cfg)
    _palette(root, spec, colors, cfg)
    ElementTree.indent(root)
    return ElementTree.tostring(root, encoding="unicode")


def _palette_x(cfg: Config) -> float:
    """Левый край палитры: правее образца стены и его отметок уровней."""
    look, lev = cfg.sheet.spec, cfg.sheet.levels
    return look.margin_m + look.wall_m + lev.offset_m + lev.shelf_right_m + look.gap_m


def _wall(root: ElementTree.Element, spec: HouseSpec, colors: dict[str, str],
          cfg: Config) -> None:
    """Образец стены: цоколь цветом роли «цоколь», выше — «основной», и отметки уровней."""
    w, ox = cfg.sheet.spec.wall_m, cfg.sheet.spec.margin_m
    oy = ox + spec.eaves_m  # земля
    fill = cfg.library.fill.wall
    # Класс фасада — ради линий из sheet.css; это не лист, разбор листа к нему не применяется.
    g = ElementTree.SubElement(root, "g", {
        "class": sheet_format.FACADE_CLASS,
        "transform": f"translate({num(ox)},{num(oy)}) scale(1,-1)"})
    bands = ((PaletteRole.MAIN, 0.0, spec.eaves_m), (PaletteRole.PLINTH, 0.0, spec.plinth_m))
    for role, y0, y1 in bands:
        if y1 > y0:
            box = [(0.0, y0), (w, y0), (w, y1), (0.0, y1)]
            ElementTree.SubElement(g, "polygon", {"points": points(box),
                                                  "fill": colors.get(role, fill)})
    silhouette = [(0.0, 0.0), (w, 0.0), (w, spec.eaves_m), (0.0, spec.eaves_m)]
    ElementTree.SubElement(g, "polygon", {"class": "outline", "points": points(silhouette)})
    a = ElementTree.SubElement(root, "g", {"class": "annotations",
                                           "transform": f"translate({num(ox)},{num(oy)})"})
    ext = cfg.sheet.ground.extend_m
    add_line(a, "ground", (-ext, 0.0), (w + ext, 0.0))
    for v in levels(spec, cfg.sheet.levels):
        level_mark(a, w + cfg.sheet.levels.offset_m, v, cfg.sheet.levels)


def _palette(root: ElementTree.Element, spec: HouseSpec, colors: dict[str, str],
             cfg: Config) -> None:
    """Материал палитры — строкой: образец его цвета и подпись «id · вид»."""
    look = cfg.sheet.spec
    x, top, s = _palette_x(cfg), look.margin_m, look.swatch_m
    for i, m in enumerate(spec.materials):
        y = top + i * look.line_m
        ElementTree.SubElement(root, "rect", {"class": "spec-swatch", "x": num(x), "y": num(y),
                                              "width": num(s), "height": num(s),
                                              "fill": colors[m.id]})
        add_text(root, "spec-label", (x + s + look.text_dx_m, y + s), f"{m.id} · {m.kind}")
