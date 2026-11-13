"""Цвета отделки дома с листа фасадов (gf#470, спека data: «Цвета отделки с чертежа»).

    python tools/markup_colors.py markup/stroim/st-*.toml [--write]

Для каждой роли палитры — медиана RGB пикселей её мест на видах дома: основная — стена стороны
до карниза без рамок элементов и зон (при силуэте — внутри него), вторая отделка — зоны `accent`,
цоколь — полоса от чистого пола до земли, карниз — элементы `cornice`, кровля — многоугольники
`roof`. Мест нет или пикселей меньше `[manual.colors] min_pixels` — роль не пишется. Без `--write`
печатает таблицу дом × роль; с `--write` вставляет в разметку строку `colors = { … }` сразу после
`material = …` (нет цветов — убирает прежнюю), остальной текст и комментарии не трогает.
"""

import argparse
import re
import sys
from pathlib import Path

import numpy
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))  # из тестов — не из папки tools
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from markup_raster import page_rgb  # noqa: E402

from genfacade.config import load  # noqa: E402
from genfacade.datasets import manual  # noqa: E402
from genfacade.schema import ElementClass, PaletteRole, ZoneRole  # noqa: E402

Polygon = list[tuple[float, float]]
Pages = dict[tuple[str, int], numpy.ndarray]
MATERIAL_LINE = re.compile(r"^material = .*$", re.MULTILINE)
COLORS_LINE = re.compile(r"^colors = .*\n", re.MULTILINE)


def rect(box: tuple[float, ...]) -> Polygon:
    x0, y0, x1, y1 = box
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def painted(size: tuple[int, int], shapes: list[Polygon]) -> numpy.ndarray:
    """Маска листа, закрашенная под многоугольниками."""
    img = Image.new("L", size, 0)
    for shape in shapes:
        ImageDraw.Draw(img).polygon(shape, fill=1)
    return numpy.asarray(img, dtype=bool)


Regions = dict[PaletteRole, tuple[list[Polygon], ...]]


def regions(m: manual.Markup, e: manual.Elevation) -> Regions:
    """Роль → (где её цвет, из чего вычесть, чем обрезать) на виде e; пустой — не обрезать."""
    wall = rect((e.wall[0], m.tops_y(e)[-1], e.wall[1], e.floor))
    below = rect((e.wall[0], 0, e.wall[1], e.floor))  # силуэт — только внутри стены, не ниже пола
    zones = [rect(z.box) for z in e.zones]  # зона на полосе цоколя — её цвет, не цоколя
    holes = [rect(b.box) for b in e.elements] + zones
    plinth = rect((e.wall[0], e.floor, e.wall[1], m.ground_y(e)))
    return {
        PaletteRole.MAIN: ([e.outline] if e.outline else [wall], holes, [below]),
        PaletteRole.ACCENT: ([rect(z.box) for z in e.zones if z.role is ZoneRole.ACCENT], [], []),
        PaletteRole.PLINTH: ([plinth] if m.plinth > 0 else [], zones, []),
        PaletteRole.TRIM: ([rect(b.box) for b in e.elements if b.cls is ElementClass.CORNICE],
                           [], []),
        PaletteRole.ROOF: (e.roof, [], []),
    }


def pixels(rgb: numpy.ndarray, shapes: list[Polygon], holes: list[Polygon], clip: list[Polygon]
           ) -> numpy.ndarray:
    """Пиксели (N, 3) под shapes без holes внутри clip (clip пуст — без обрезки)."""
    size = (rgb.shape[1], rgb.shape[0])
    mask = painted(size, shapes) if shapes else numpy.zeros(rgb.shape[:2], dtype=bool)
    if clip:
        mask &= painted(size, clip)
    if holes:
        mask &= ~painted(size, holes)
    return rgb[mask]


def page(pdf: Path, number: int, pages: Pages) -> numpy.ndarray:
    key = (str(pdf), number)
    if key not in pages:
        pages[key] = numpy.asarray(page_rgb(*key))
    return pages[key]


def collect(m: manual.Markup, pdf: Path, pages: Pages) -> dict[PaletteRole, numpy.ndarray]:
    """Пиксели каждой роли со всех видов дома."""
    found: dict[PaletteRole, list[numpy.ndarray]] = {r: [] for r in PaletteRole}
    for e in m.sides:
        rgb = page(pdf, e.page, pages)
        for role, (shapes, holes, clip) in regions(m, e).items():
            found[role].append(pixels(rgb, shapes, holes, clip))
    return {role: numpy.concatenate(parts) for role, parts in found.items()}


def median_color(px: numpy.ndarray, cfg: manual.Manual) -> str | None:
    """`#rrggbb` медианы без линий чертежа; пикселей меньше порога — нет цвета."""
    px = px[px.mean(axis=1) >= cfg.colors.line_dark]
    if len(px) < cfg.colors.min_pixels:
        return None
    r, g, b = (int(v) for v in numpy.median(px, axis=0))
    return f"#{r:02x}{g:02x}{b:02x}"


def house_colors(path: Path, cfg: manual.Manual, pages: Pages) -> dict[PaletteRole, str]:
    m = manual.read(path)
    pdf = cfg.paths.pdf_dirs[path.parent.name] / m.pdf
    roles = manual.palette_roles(m)  # цвет роли без материала разметка не принимает
    found = {role: median_color(px, cfg) for role, px in collect(m, pdf, pages).items()
             if role in roles}
    return {role: color for role, color in found.items() if color}


def colors_line(colors: dict[PaletteRole, str]) -> str:
    return "colors = { " + ", ".join(f'{r} = "{c}"' for r, c in colors.items()) + " }\n"


def write(path: Path, colors: dict[PaletteRole, str]) -> None:
    """Строка `colors` — сразу после `material`; прежняя заменяется, остальной текст — как был."""
    text = COLORS_LINE.sub("", path.read_text())
    if not colors:
        path.write_text(text)
        return
    line = MATERIAL_LINE.search(text)
    if line is None:
        raise ValueError(f"{path}: нет строки material")
    path.write_text(f"{text[:line.end() + 1]}{colors_line(colors)}{text[line.end() + 1:]}")


def arguments() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    p.add_argument("markup", nargs="+", type=Path)
    p.add_argument("--write", action="store_true", help="записать строку colors в разметку")
    return p.parse_args()


def main() -> None:
    a = arguments()
    cfg, pages = load().data.manual, {}
    print("дом       " + " ".join(f"{r:8}" for r in PaletteRole))
    for path in a.markup:
        colors = house_colors(path, cfg, pages)
        print(f"{path.stem:9} " + " ".join(f"{colors.get(r, '-'):8}" for r in PaletteRole))
        if a.write:
            write(path, colors)
        pages.clear()  # лист дома другому не нужен: держать все 29 в памяти незачем


if __name__ == "__main__":
    main()
