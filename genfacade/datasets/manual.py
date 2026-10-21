"""Ручная разметка реальных коттеджей → примеры теста (`data: Реальные коттеджи — тест`, gf#180).

Разметка — TOML на дом. Координаты элементов — прямоугольники в pt листа PDF (x вправо, y вниз),
как их снимает разметчик с векторного листа фасада; отметки — в футах с листа (цоколь, этажи до
карниза). Перевод в метры — здесь, по масштабу листа `pt_per_ft`. Стороны — четыре, по часовой
стрелке от стороны входа; у каждой — левый и правый край стены и отметка чистого пола в pt.

Что выше карниза и чего формат не держит (скаты, фронтоны, мансарды), разметчик не размечает, а
перечисляет в `cut` — это идёт в опись (`data: Стена до карниза в данных`); элемент, заходящий
за карниз или угол, обрезается по стене.
"""

import tomllib
from collections import Counter
from pathlib import Path

import numpy
from pydantic import Field

from genfacade.config import Config, Manual
from genfacade.datasets import rect_house, store
from genfacade.schema import (
    BuildingType,
    Element,
    ElementClass,
    HouseSpec,
    Material,
    Model,
    OpeningVariant,
    PaletteRole,
    Roof,
    RoofKind,
    Sample,
    Source,
    Split,
)
from genfacade.validate import errors, validate

M_PER_FT = 0.3048  # международный фут — определение единицы, не настройка

SIDES = 4  # прямоугольник; сторона k разметки — стена k в rect_house.NORMALS: вход смотрит в +y


class NotRectangle(Exception):
    """Разметка не прямоугольного дома: развёртка его не примет (дом — на потом)."""


class Mark(Model):
    """Элемент на листе: прямоугольник x0, верх, x1, низ в pt."""

    cls: ElementClass
    box: tuple[float, float, float, float]
    variant: OpeningVariant | None = None
    parent: int | None = None  # номер окна в списке стороны: у ставен, подоконника


class Elevation(Model):
    view: str            # подпись вида на листе: по ней разметку сверяют с PDF
    page: int = Field(ge=1)
    wall: tuple[float, float]  # левый и правый край стены, pt
    floor: float         # отметка чистого пола первого этажа, pt
    elements: list[Mark] = []


class Markup(Model):
    id: str
    pdf: str             # имя листа в pdf/ рядом с разметкой
    roof: str            # исходный вид крыши — в опись: формат держит только плоскую
    pt_per_ft: float = Field(gt=0)
    material: str        # вид основной отделки из library.toml
    plinth_ft: float = Field(ge=0)    # чистый пол над землёй
    floor_heights_ft: list[float]     # этажи от чистого пола до карниза
    cut: list[str] = []  # срезанное разметчиком: что и с какой стороны
    sides: list[Elevation]


def read(path: Path) -> Markup:
    return Markup.model_validate(tomllib.loads(path.read_text()))


def house(m: Markup, cfg: Manual) -> tuple[Sample, int]:
    """Пример дома и сколько элементов обрезано целиком (за карнизом или углом)."""
    lengths = _lengths(m, cfg)
    spec = _spec(m)
    fp = rect_house.Footprint(numpy.zeros(2), numpy.array(lengths[:2]), cfg.wall_m)
    laid, dropped = [], 0
    for k, e in enumerate(m.sides):
        elements = _side_elements(e, m, spec)
        kept = [x for x in (_clipped(x, lengths[k], spec, cfg) for x in elements) if x]
        dropped += len(elements) - len(kept)
        laid.append((k, kept))
    plan, sheet = rect_house.assemble(spec, fp, laid, Source.MANUAL)
    return Sample(id=m.id, source=Source.MANUAL, split=Split.TEST, plan=plan, sheet=sheet), dropped


def _lengths(m: Markup, cfg: Manual) -> list[float]:
    if len(m.sides) != SIDES:
        raise NotRectangle(f"{m.id}: сторон {len(m.sides)}, нужно {SIDES}")
    lengths = [(e.wall[1] - e.wall[0]) / m.pt_per_ft * M_PER_FT for e in m.sides]
    for k in range(2):
        if abs(lengths[k] - lengths[k + 2]) > cfg.length_tol_m:
            raise NotRectangle(f"{m.id}: стороны {k} и {k + 2} — {lengths[k]:.2f} и "
                               f"{lengths[k + 2]:.2f} м")
    return lengths


def _spec(m: Markup) -> HouseSpec:
    plinth, heights = m.plinth_ft * M_PER_FT, [h * M_PER_FT for h in m.floor_heights_ft]
    return HouseSpec(building_type=BuildingType.COTTAGE, floors=len(heights),
                     floor_heights_m=heights, plinth_m=plinth, eaves_m=plinth + sum(heights),
                     roof=Roof(kind=RoofKind.FLAT),
                     materials=[Material(id=PaletteRole.MAIN, kind=m.material)])


def _side_elements(e: Elevation, m: Markup, spec: HouseSpec) -> list[Element]:
    """Прямоугольники листа → элементы стены: x от левого края, y от земли, метры."""
    def metres(v: float) -> float:
        return v / m.pt_per_ft * M_PER_FT

    out = []
    for n, mark in enumerate(e.elements):
        x0, top, x1, bottom = (metres(v) for v in mark.box)
        y0 = spec.plinth_m + metres(e.floor) - bottom
        out.append(Element(id=f"e{n}", cls=mark.cls, x_m=x0 - metres(e.wall[0]), y_m=y0,
                           w_m=x1 - x0, h_m=bottom - top, variant=mark.variant,
                           parent=None if mark.parent is None else f"e{mark.parent}",
                           floor=rect_house.floor_of(y0 + (bottom - top) / 2, spec)))
    return out


def _clipped(x: Element, length: float, spec: HouseSpec, cfg: Manual) -> Element | None:
    """Обрезать по стене до карниза; внутри меньше inside_share — элемента нет."""
    x0, y0 = max(x.x_m, 0.0), max(x.y_m, 0.0)
    x1, y1 = min(x.x_m + x.w_m, length), min(x.y_m + x.h_m, spec.eaves_m)
    if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) < cfg.inside_share * x.w_m * x.h_m:
        return None
    return x.model_copy(update={"x_m": x0, "y_m": y0, "w_m": x1 - x0, "h_m": y1 - y0})


def run(cfg: Config) -> Path:
    """Все разметки папки → примеры и опись: срезанное, исходные крыши, ошибки валидатора."""
    rules, root = cfg.data.manual, cfg.data.paths.samples_dir
    # Источник целиком — производное разметки: удалённая разметка не должна оставить пример.
    for old in store.ids(root, Source.MANUAL):
        store.path(root, Source.MANUAL, old).unlink()
    rejected, cut, roofs, invalid = {}, {}, {}, Counter()
    for path in sorted(rules.paths.markup_dir.glob("*.toml")):
        m = read(path)
        try:
            sample, dropped = house(m, rules)
        except NotRectangle as e:
            rejected[m.id] = str(e)
            continue
        cut[m.id], roofs[m.id] = len(m.cut) + dropped, m.roof
        invalid.update(v.rule for v in errors(validate(sample.sheet, cfg.checks)))
        store.write(sample, root)
    return store.write_manifest(root, Source.MANUAL, {
        "rejected": rejected, "cut": cut, "roofs": roofs, "invalid": dict(invalid)})
