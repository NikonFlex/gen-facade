"""Ручная разметка реальных коттеджей → примеры теста (`data: Реальные коттеджи — тест`, gf#180).

Разметка — TOML на дом. Координаты элементов — прямоугольники в pt листа PDF (x вправо, y вниз),
как их снимает разметчик с векторного листа фасада; отметки — в футах с листа (цоколь, этажи до
карниза). Перевод в метры — здесь, по масштабу листа `pt_per_ft`. Стороны — по часовой стрелке от
стороны входа, контур ортогональный: у каждой — левый и правый край стены и отметка чистого пола в
pt, и внутренний ли угол после неё (Г-, Т-контур, gf#199).

Что выше карниза и чего формат не держит (скаты, фронтоны, мансарды), разметчик не размечает, а
перечисляет в `cut` — это идёт в опись (`data: Стена до карниза в данных`); элемент, заходящий
за карниз или угол, обрезается по стене.

Подоконник, ставни, наличник и козырёк модель шага 4 пишет признаком своего проёма (gf#212): их
связь с проёмом — родитель. Где разметчик родителя не указал, он ставится по месту (`_linked`); вид
этих элементов у дома — по умолчанию из настроек, для тех, что у дома есть.
"""

import math
import tomllib
from collections import Counter
from pathlib import Path

import numpy
from pydantic import Field

from genfacade import derive
from genfacade.config import Config, Manual
from genfacade.datasets import rect_house, store
from genfacade.schema import (
    EPS,
    BuildingType,
    Element,
    ElementClass,
    HouseSpec,
    HouseTrim,
    Material,
    Model,
    OpeningVariant,
    PaletteRole,
    Roof,
    RoofKind,
    Sample,
    Source,
    Split,
    Trim,
)
from genfacade.validate import errors, validate

M_PER_FT = 0.3048  # международный фут — определение единицы, не настройка

FIRST_NORMAL = (0.0, 1.0)  # сторона входа смотрит в +y плана (rect_house.NORMALS[0])


class BadContour(Exception):
    """Стороны разметки не складываются в замкнутый ортогональный контур по часовой."""


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
    inner_corner: bool = False  # угол после этой стороны — внутренний (Г-, Т-контур, gf#199)


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
    fp = _outline(m, cfg)
    lengths = [w.length for w in fp.walls]
    spec = _spec(m)
    laid, dropped = [], 0
    for k, e in enumerate(m.sides):
        elements = _side_elements(e, m, spec)
        kept = [x for x in (_clipped(x, lengths[k], spec, cfg) for x in elements) if x]
        dropped += len(elements) - len(kept)
        laid.append((k, _linked(kept, cfg.link_tol_m)))
    spec = spec.model_copy(update={"trim": _trim([xs for _, xs in laid], cfg.trim)})
    plan, sheet = rect_house.assemble(spec, fp, laid, Source.MANUAL)
    return Sample(id=m.id, source=Source.MANUAL, split=Split.TEST, plan=plan, sheet=sheet), dropped


def _outline(m: Markup, cfg: Manual) -> rect_house.Footprint:
    """Контур по сторонам разметки: длины — с листов, повороты — внешний угол (−90°) или
    внутренний (+90°). Невязка обхода в пределах length_tol_m снимается с последних сторон вдоль
    x и вдоль y: листы фасадов меряют стену с точностью обшивки, а не каркаса."""
    normals, n = [], FIRST_NORMAL
    for e in m.sides:
        normals.append(n)
        n = (-n[1] + 0.0, n[0] + 0.0) if e.inner_corner else (n[1] + 0.0, -n[0] + 0.0)
    if n != FIRST_NORMAL or len(m.sides) < 4:
        raise BadContour(f"{m.id}: повороты сторон не замыкают обход по часовой")
    lengths = [(e.wall[1] - e.wall[0]) / m.pt_per_ft * M_PER_FT for e in m.sides]
    steps = [numpy.array((ny, -nx)) for nx, ny in normals]  # по часовой: нормаль на −90°
    gap = sum(d * length for d, length in zip(steps, lengths, strict=True))
    if numpy.hypot(*gap) > cfg.length_tol_m:
        raise BadContour(f"{m.id}: контур не замкнулся — невязка {numpy.hypot(*gap):.2f} м")
    for axis in (0, 1):
        k = max(i for i, d in enumerate(steps) if d[axis])
        lengths[k] -= gap[axis] / steps[k][axis]
    corners = [numpy.zeros(2)]
    for d, length in zip(steps[:-1], lengths[:-1], strict=True):
        corners.append(corners[-1] + d * length)
    low = numpy.min(corners, axis=0)  # план — от (0, 0), как у прямоугольника прежде
    return rect_house.Footprint([c - low for c in corners], normals, cfg.wall_m)


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


def _linked(elements: list[Element], tol: float) -> list[Element]:
    """Выводимый элемент без родителя → родитель — проём по месту; места нет — без родителя."""
    out = []
    for x in elements:
        trim = derive.TRIM_OF.get(x.cls)
        if trim is None or x.parent is not None:
            out.append(x)
            continue
        owners = [o for o in elements if o.cls is derive.OWNER[trim]]
        # козырёк — над дверью на любой высоте: навес крыльца разметчик снимает до свеса
        reach = math.inf if trim is Trim.CANOPY else tol
        near = [(gap, o.id) for o in owners if (gap := _gap(x, o, trim)) is not None
                and gap <= reach]
        out.append(x.model_copy(update={"parent": min(near)[1]}) if near else x)
    return out


def _gap(x: Element, o: Element, trim: Trim) -> float | None:
    """Зазор от выводимого элемента до проёма на своём месте: подоконник под окном, ставня сбоку,
    козырёк над дверью (наличник — вокруг окна); не на своём месте — None."""
    def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
        return min(a1, b1) - max(a0, b0)

    across = overlap(x.x_m, x.x_m + x.w_m, o.x_m, o.x_m + o.w_m)
    along = overlap(x.y_m, x.y_m + x.h_m, o.y_m, o.y_m + o.h_m)
    if trim is Trim.SHUTTERS:
        return max(0.0, -across) if along >= o.h_m / 2 else None
    if trim is Trim.SILL:
        return abs(x.y_m + x.h_m - o.y_m) if across >= o.w_m / 2 else None
    if trim is Trim.CANOPY:
        return max(0.0, x.y_m - o.y_m - o.h_m) if across > EPS and x.y_m + EPS >= o.y_m else None
    return 0.0 if across >= o.w_m - EPS and along >= o.h_m - EPS else None


def _trim(walls: list[list[Element]], kinds: HouseTrim) -> HouseTrim:
    """Виды выводимых элементов дома: по умолчанию — у тех, что есть у проёмов его стен;
    остальные — none (у дома их нет). Имена элементов — свои у каждой стены."""
    present = {t for wall in walls for marks in derive.flags(wall).values() for t in marks}
    return HouseTrim(**{t: kinds.kind(t) if t in present else HouseTrim().kind(t) for t in Trim})


def run(cfg: Config) -> Path:
    """Все разметки папки → примеры и опись: срезанное, исходные крыши, ошибки валидатора."""
    rules, root = cfg.data.manual, cfg.data.paths.samples_dir
    # Источник целиком — производное разметки: удалённая разметка не должна оставить пример.
    for old in store.ids(root, Source.MANUAL):
        store.path(root, Source.MANUAL, old).unlink()
    rejected, cut, roofs, invalid = {}, {}, {}, Counter()
    for path in sorted(rules.paths.markup_dir.glob("*/*.toml")):
        m = read(path)
        try:
            sample, dropped = house(m, rules)
        except BadContour as e:
            rejected[m.id] = str(e)
            continue
        cut[m.id], roofs[m.id] = len(m.cut) + dropped, m.roof
        invalid.update(v.rule for v in errors(validate(sample.sheet, cfg.checks)))
        store.write(sample, root)
    return store.write_manifest(root, Source.MANUAL, {
        "rejected": rejected, "cut": cut, "roofs": roofs, "invalid": dict(invalid)})
