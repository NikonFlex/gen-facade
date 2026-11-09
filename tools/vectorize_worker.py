"""Готовый векторизатор растра → цветные области с рамками (gf#17, `genfacade vectorize`).

Запускается интерпретатором отдельного venv, где стоят сторонние библиотеки (EvoVec из VGLib,
vtracer, svgpathtools) — проект их не тянет. Читает `settings.json`, для каждого растра .npy
папки пишет `<имя>.json`:

    {"seconds": …, "shapes": [{"color": [r, g, b], "box": [x0, y0, x1, y1], "segments": n}]}

— путь результата, его осевая рамка в пикселях растра и число сегментов. Что считать классом и
как перевести в метры — дело проекта (`genfacade/vectorizer.py`); здесь только запуск чужого кода.

    python tools/vectorize_worker.py settings.json <папка растров .npy> <папка ответов> <k> <n>

k из n — доля файлов: так несколько процессов делят папку. Готовый ответ не пересчитывается.
"""

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from xml.etree import ElementTree

import svgpathtools

SVG_NS = "{http://www.w3.org/2000/svg}"
RGB = re.compile(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)")
HEX = re.compile(r"#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})")
URL = re.compile(r"url\(#([^)]+)\)")


def color_of(text: str) -> list[int] | None:
    """Цвет заливки rgb(…) или #rrggbb."""
    if found := RGB.search(text):
        return [int(g) for g in found.groups()]
    if found := HEX.search(text):
        return [int(g, 16) for g in found.groups()]
    return None


def gradients(root: ElementTree.Element) -> dict[str, list[int]]:
    """Градиент EvoVec (слитые пути) → средний цвет его остановок."""
    out = {}
    for g in root.iter(f"{SVG_NS}linearGradient"):
        stops = [color_of(s.get("stop-color", "")) for s in g.iter(f"{SVG_NS}stop")]
        stops = [s for s in stops if s]
        if stops:
            out[g.get("id")] = [round(sum(c) / len(stops)) for c in zip(*stops, strict=True)]
    return out


def shift(node: ElementTree.Element) -> tuple[float, float]:
    """transform="translate(x,y)" у пути vtracer."""
    found = re.search(r"translate\(\s*([-\d.]+)[ ,]+([-\d.]+)\s*\)", node.get("transform", ""))
    return (float(found.group(1)), float(found.group(2))) if found else (0.0, 0.0)


def shapes(svg: str) -> list[dict]:
    """Все пути SVG: цвет заливки и осевая рамка (по кривым, а не по опорным точкам)."""
    root = ElementTree.fromstring(svg)  # noqa: S314 — SVG пишет векторизатор на этой машине
    grads, out = gradients(root), []
    for node in root.iter(f"{SVG_NS}path"):
        fill = node.get("fill", "")
        link = URL.search(fill)
        color = grads.get(link.group(1)) if link else color_of(fill)
        if color is None or not node.get("d"):
            continue
        path = svgpathtools.parse_path(node.get("d"))
        x0, x1, y0, y1 = path.bbox()
        dx, dy = shift(node)
        out.append({"color": color, "box": [x0 + dx, y0 + dy, x1 + dx, y1 + dy],
                    "segments": len(path)})
    return out


def to_png(raster: Path, work: Path) -> Path:
    """Растр стены проекта (.npy, H×W×3 uint8) → PNG: сторонний код читает файлы картинок."""
    import numpy
    from PIL import Image

    png = work / "wall.png"
    Image.fromarray(numpy.load(raster)).save(png)
    return png


def run_vtracer(png: Path, settings: dict, work: Path) -> str:
    import vtracer

    target = work / "out.svg"
    vtracer.convert_image_to_svg_py(str(png), str(target), **settings["vtracer"])
    return target.read_text()


class EvoVec:
    """EvoVec без правок кода: цикл `main.main` без отладочной печати, gif и pdf — результат
    возвращается, а не остаётся в tmp/. Копия папки у каждого процесса: код пишет в свои tmp."""

    def __init__(self, settings: dict, work: Path) -> None:
        folder = work / "evovec"
        shutil.rmtree(folder, ignore_errors=True)
        shutil.copytree(settings["evovec"]["code"], folder)
        os.chdir(folder)
        sys.path.insert(0, str(folder))
        os.makedirs("tmp", exist_ok=True)
        import svgtrace

        # svgtrace зовёт install_playwright.install(браузер) в виде, который у новых версий
        # пакета падает; браузер на машине уже стоит.
        svgtrace.install = lambda *args, **kwargs: None
        import config
        import main

        config.DEBUG = False
        config.STEP_EVOL = settings["evovec"]["generations"]
        config.INDIVIDUAL_COUNT = settings["evovec"]["individuals"]
        self.config, self.main = config, main

    def __call__(self, png: Path, settings: dict, work: Path) -> str:
        import cache

        cache.PNG_IMAGE = None  # кэш картинки в модуле — от прошлого дома
        self.config.PNG_PATH = str(png)
        generation = self.main.init_first_generation()
        for step in range(self.config.STEP_EVOL):
            elite = self.main.get_most_fittest(generation, int(self.config.ELITE_PERCENT
                                                               * self.config.INDIVIDUAL_COUNT))
            children = self.main.mutation(self.main.create_children(elite), step)
            generation = self.main.get_most_fittest(
                elite + self.main.crossover(children), self.config.INDIVIDUAL_COUNT)
        target = work / "out.svg"
        generation[0].save_as_svg(str(target))
        return target.read_text()


def main() -> None:
    settings_path, images, out, k, n = sys.argv[1:6]
    settings = json.loads(Path(settings_path).read_text())
    out_dir = Path(out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(settings["work"]).resolve() / f"shard-{k}"
    work.mkdir(parents=True, exist_ok=True)
    files = [p.resolve() for p in sorted(Path(images).glob("*.npy"))][int(k)::int(n)]
    vectorize = EvoVec(settings, work) if settings["backend"] == "evovec" else run_vtracer
    for raster in files:
        target = out_dir / f"{raster.stem}.json"
        if target.exists():
            continue
        started = time.time()
        svg = vectorize(to_png(raster, work), settings, work)
        target.write_text(json.dumps({"seconds": round(time.time() - started, 2),
                                      "shapes": shapes(svg)}))
        print(raster.stem, round(time.time() - started, 1), flush=True)


if __name__ == "__main__":
    main()
