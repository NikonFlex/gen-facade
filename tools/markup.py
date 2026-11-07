"""Ручная разметка реальных коттеджей (gf#180): подсказка с листа и сверка разметки с исходником.

    python tools/markup.py hint <pdf> <стр> <x0,y0,x1,y1> <pt на фут>
    python tools/markup.py overlay <разметка.toml>... [-o outputs/markup] [--dpi 100]
    python tools/markup.py grid <pdf> <стр> <x0,y0,x1,y1> [--zoom 2] [-o grid.png]  растр, gf#328
    python tools/markup.py snap <pdf> <стр> <x0,y0,x1,y1>   края прикидки — к линиям растра

overlay — кадр каждого фасада из PDF, поверх — края стены, чистый пол, земля, карниз и рамки
элементов; картинка на дом — стороны по две в ряд.

Цвета: стена и уровни — синие, окна — красные, двери и ворота — зелёные, прочее (и карниз) —
оранжевое, зоны второй отделки — малиновые, с подписью роли и материала (gf#245). Запись выше
карниза (gf#323): силуэт стены — голубой, участки карниза — синие толстые с числом этажей, крыша —
коричневая.
Нужен pdfplumber (dev-зависимости).
"""

import argparse
import sys
from pathlib import Path

import pdfplumber
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from markup_hint import hint  # noqa: E402
from markup_raster import grid, snap  # noqa: E402

from genfacade.config import load  # noqa: E402
from genfacade.datasets import manual  # noqa: E402

PT = 72.0          # pt на дюйм — определение единицы
MARGIN_M = 0.9     # поле вокруг стены на кадре, метры
LEVELS, WINDOW, DOOR, OTHER, ZONE = "blue", "red", "green", "orange", "magenta"
OUTLINE, ROOF = "deepskyblue", "saddlebrown"
DOORS = {"door", "garage_door"}


def font(size: int) -> ImageFont.ImageFont:
    """Шрифт с кириллицей, если есть в системе; иначе встроенный (подписи по-русски — квадраты)."""
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def frame(pdf: Path, e: manual.Elevation, m: manual.Markup, dpi: int) -> tuple[Image.Image, tuple]:
    """Кадр стороны: от карниза до земли и от края до края стены с полем."""
    pad = MARGIN_M / m.m_per_unit * m.scale(e)
    eaves = e.floor - sum(m.floor_heights) * m.scale(e)
    tops = [b.box[1] for b in e.elements] + [eaves] + [y for _, y in e.outline] + [
        y for shape in e.roof for _, y in shape]
    box = (e.wall[0] - pad, min(tops) - pad, e.wall[1] + pad,
           e.floor + m.plinth * m.scale(e) + pad)
    with pdfplumber.open(pdf) as doc:
        page = doc.pages[e.page - 1]
        box = (max(box[0], 0), max(box[1], 0), min(box[2], page.width), min(box[3], page.height))
        return page.crop(box).to_image(resolution=dpi).original.convert("RGB"), box


def draw(img: Image.Image, box: tuple, e: manual.Elevation, m: manual.Markup, dpi: int) -> None:
    k = dpi / PT
    d = ImageDraw.Draw(img)

    def px(x: float, y: float) -> tuple[float, float]:
        return (x - box[0]) * k, (y - box[1]) * k

    levels = [e.floor, e.floor + m.plinth * m.scale(e)]
    y = e.floor
    for h in m.floor_heights:
        y -= h * m.scale(e)
        levels.append(y)
    for v in levels:
        d.line([px(e.wall[0], v), px(e.wall[1], v)], fill=LEVELS, width=1)
    for x in e.wall:
        d.line([px(x, levels[-1]), px(x, levels[1])], fill=LEVELS, width=2)
    for n, b in enumerate(e.elements):
        color = WINDOW if b.cls == "window" else DOOR if b.cls in DOORS else OTHER
        d.rectangle([px(b.box[0], b.box[1]), px(b.box[2], b.box[3])], outline=color, width=2)
        d.text(px(b.box[0] + 2, b.box[1] + 1), str(n), fill=color, font=font(12))
    for z in e.zones:
        d.rectangle([px(z.box[0], z.box[1]), px(z.box[2], z.box[3])], outline=ZONE, width=2)
        d.text(px(z.box[0] + 2, z.box[3] - 14), f"{z.role} {z.material}", fill=ZONE, font=font(12))
    above(d, px, e)
    d.text((4, 4), f"{e.view} (стр. {e.page})", fill="black", font=font(14))


def above(d: ImageDraw.ImageDraw, px, e: manual.Elevation) -> None:
    """Запись чертежа выше карниза и по участкам (gf#323): силуэт, участки карниза, крыша."""
    for shape, color in [(e.outline, OUTLINE), *((r, ROOF) for r in e.roof)]:
        if shape:
            d.line([px(*p) for p in [*shape, shape[0]]], fill=color, width=2)
    for s in e.eaves:
        d.line([px(s.x[0], s.y), px(s.x[1], s.y)], fill=LEVELS, width=4)
        d.text(px(s.x[0] + 2, s.y - 14), f"{s.floors} эт.", fill=LEVELS, font=font(12))


def sheet(path: Path, pdf_dirs: dict[str, Path], dpi: int) -> Image.Image:
    m = manual.read(path)
    tiles = []
    for e in m.sides:
        img, box = frame(pdf_dirs[path.parent.name] / m.pdf, e, m, dpi)
        draw(img, box, e, m, dpi)
        tiles.append(img)
    w, h = max(t.width for t in tiles), max(t.height for t in tiles)
    rows = (len(tiles) + 1) // 2
    out = Image.new("RGB", (2 * w + 10, rows * (h + 10) + 30), "white")
    for k, t in enumerate(tiles):  # по две стороны в ряд, по часовой от стороны входа
        out.paste(t, ((k % 2) * (w + 10), 30 + (k // 2) * (h + 10)))
    ImageDraw.Draw(out).text((4, 4), f"{m.id}: {m.roof}", fill="black", font=font(18))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    h = sub.add_parser("hint", help="линии и пути листа в кадре")
    h.add_argument("pdf")
    h.add_argument("page", type=int)
    h.add_argument("box", help="x0,y0,x1,y1 в pt")
    h.add_argument("pt_per_ft", type=float)
    for name, text in (("grid", "кадр растрового листа с линейкой в pt (gf#328)"),
                       ("snap", "края прикидки рамки — к тёмным линиям растрового листа")):
        r = sub.add_parser(name, help=text)
        r.add_argument("pdf")
        r.add_argument("page", type=int)
        r.add_argument("box", help="x0,y0,x1,y1 в pt")
    sub.choices["grid"].add_argument("--zoom", type=int, default=2)
    sub.choices["grid"].add_argument("-o", "--out", type=Path,
                                     default=Path("outputs/markup/grid.png"))
    v = sub.add_parser("overlay", help="разметка поверх исходного листа")
    v.add_argument("markup", nargs="+", type=Path)
    v.add_argument("-o", "--out", type=Path, default=Path("outputs/markup"))
    v.add_argument("--dpi", type=int, default=100)
    a = p.parse_args()
    if a.command in ("grid", "snap"):
        box = tuple(map(float, a.box.split(",")))
        if a.command == "snap":
            print(",".join(map(str, snap(a.pdf, a.page, box))))
            return
        a.out.parent.mkdir(parents=True, exist_ok=True)
        grid(a.pdf, a.page, box, a.zoom).save(a.out)
        print(a.out)
        return
    if a.command == "hint":
        print(hint(a.pdf, a.page, tuple(map(float, a.box.split(","))), a.pt_per_ft))
        return
    pdf_dirs = load().data.manual.paths.pdf_dirs
    a.out.mkdir(parents=True, exist_ok=True)
    for path in a.markup:
        target = a.out / f"{path.stem}.png"
        sheet(path, pdf_dirs, a.dpi).save(target)
        print(target)


if __name__ == "__main__":
    main()
