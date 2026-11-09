"""Растр от генератора вместо рендера эталона (gf#17, «генератор → векторизатор»).

Тот же базовый подход, что `vectorizer`, но картинку стены рисует не код, а диффузионная модель:
А — SDXL по тексту (глухой режим), Б — SD 1.5 с ControlNet по маске окон и дверей плана. Дальше
картинка идёт в vtracer и OWLv2, а найденные рамки в метрах — в `Extracted`, и `genfacade realtest
--vectorized ИМЯ=ПАПКА` строит строку. Здесь — то, что не требует GPU: промпт из параметров дома,
размер картинки по пропорции стены, маска для ControlNet, мост «рамки в пикселях → элементы».
Сами модели грузит `tools/genbase.py`. Зон, цоколя и карниза генератор не даёт: стена — одной
отделкой, как у контроля.
"""

from collections.abc import Callable

import numpy
from PIL import Image

from genfacade import vectorizer
from genfacade.config import Config
from genfacade.metrics import visual
from genfacade.schema import (
    Element,
    ElementClass,
    HouseSpec,
    Material,
    PaletteRole,
    SideFacade,
)

OPENINGS = (ElementClass.WINDOW, ElementClass.DOOR)

Found = tuple[tuple[float, float, float, float], ElementClass]  # рамка в px картинки, класс
Detect = Callable[[Image.Image], list[Found]]


def size(f: SideFacade, spec: HouseSpec, long_side: int, cfg: Config) -> tuple[int, int]:
    """Ширина и высота картинки по пропорции стены (до карниза): длинная сторона — `long_side`,
    короткая не меньше `min_side_px`, обе кратны `step_px`."""
    run = cfg.baselines.generator.size
    width_m, height_m = f.side.length_m, spec.eaves_m
    scale = long_side / max(width_m, height_m)

    def snap(value: float) -> int:
        return max(run.step_px, round(value / run.step_px) * run.step_px)

    return (snap(max(width_m * scale, run.min_side_px)),
            snap(max(height_m * scale, run.min_side_px)))


def color_name(hex_: str, cfg: Config) -> str:
    """Ближайшее по цвету слово из `[generator.prompt.colors]`."""
    target = visual.rgb(hex_)
    names = cfg.baselines.generator.prompt.colors
    return min(names, key=lambda n: sum((a - b) ** 2 for a, b in zip(visual.rgb(names[n]), target,
                                                                      strict=True)))


def _walls(material: Material, cfg: Config) -> str:
    hex_ = material.color or cfg.library.kinds[material.kind]
    return f"{color_name(hex_, cfg)} {material.kind.replace('_', ' ')}"


def prompt(spec: HouseSpec, cfg: Config) -> str:
    """Текст картинки: описание дома из параметров шага 1 (этажи, вид, стены, крыша) и приписка
    «чертёж фасада»; модель текста не видит — только эти слова."""
    run = cfg.baselines.generator.prompt
    main = next(m for m in spec.materials if m.id == PaletteRole.MAIN)
    house = run.house.format(floors=spec.floors, building=spec.building_type.value,
                             walls=_walls(main, cfg), roof=spec.roof.kind.value)
    return f"{house}, {run.drawing}"


def control(f: SideFacade, spec: HouseSpec, width_px: int, height_px: int,
            cfg: Config) -> numpy.ndarray:
    """Маска ControlNet H×W×3: стена цветом facade, окна и двери плана — своими цветами. Стена
    сжата или растянута в картинку целиком: масштаб по осям разный, как у картинки."""
    run = cfg.baselines.generator.cnet
    colors = {ElementClass.FACADE: run.facade, ElementClass.WINDOW: run.window,
              ElementClass.DOOR: run.door}
    settings = cfg.metrics.visual.model_copy(update={
        "px_per_m": width_px / f.side.length_m, "canvas_m": (f.side.length_m, spec.eaves_m),
        "background": run.background, "colors": colors})
    walls = f.model_copy(update={"elements": [e for e in f.elements if e.cls in OPENINGS]})
    image = visual.mask(walls, spec, settings)
    if image.shape[:2] == (height_px, width_px):
        return image
    return numpy.asarray(Image.fromarray(image).resize((width_px, height_px), Image.NEAREST))


def plausible(box: tuple[float, float, float, float], image: Image.Image, cfg: Config) -> bool:
    """Размер рамки в долях стены: отсев щелей и целых стен."""
    run = cfg.baselines.generator.detect
    width, height = (box[2] - box[0]) / image.width, (box[3] - box[1]) / image.height
    return run.min_w < width < run.max_w and run.min_h < height < run.max_h


def elements(found: list[Found], image: Image.Image, f: SideFacade, spec: HouseSpec,
             cfg: Config) -> list[Element]:
    """Рамки в пикселях картинки → элементы стены в метрах. Картинка — вся стена до карниза, у неё
    свой масштаб по каждой оси (пропорция округлена до шага); `place` считает метры от левого низа
    стены и этаж, поэтому рамка приводится к квадратным пикселям высоты."""
    ppm_y = image.height / spec.eaves_m
    stretch = ppm_y / (image.width / f.side.length_m)
    out = []
    for k, (box, cls) in enumerate(found):
        if not plausible(box, image, cfg):
            continue
        square = (box[0] * stretch, box[1], box[2] * stretch, box[3])
        out.append(Element(id=f"g{k + 1}", cls=cls, **vectorizer.place(square, ppm_y, spec)))
    return out


def bridge(image: Image.Image, f: SideFacade, spec: HouseSpec, detect: Detect,
           cfg: Config) -> list[Element]:
    """Картинка стены → элементы: детектор окон и дверей и перевод рамок в метры."""
    return elements(detect(image), image, f, spec, cfg)

