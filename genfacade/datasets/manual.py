"""Ручная разметка реальных коттеджей → примеры теста (`data: Реальные коттеджи — тест`, gf#180).

Разметка — TOML на дом. Координаты элементов — прямоугольники в pt листа PDF (x вправо, y вниз),
как их снимает разметчик с листа фасада; отметки (цоколь, этажи до карниза) — в единицах листа
`unit`: футах у американских листов, метрах у российских. Перевод в метры — здесь, по масштабу листа
`pt_per_unit`. Стороны — по часовой стрелке от стороны входа, контур ортогональный: у каждой — левый
и правый край стены и отметка чистого пола в pt, и внутренний ли угол после неё (Г-, Т-контур,
gf#199).

Разметка — запись чертежа целиком, а не подгонка под модуль (gf#323): силуэт стены с фронтоном или
ступенью (`outline`), участки карниза со своей этажностью (`eaves`), крыша на виде (`roof`) и
элементы выше карниза. Вид, уклон и свес крыши дома — полями разметки (`roof_kind`, `pitch_deg`,
`overhang_m`, gf#336): с gf#320 вид крыши — условие модели шага 4 и решает, у каких стен
карниз. Сборщик берёт то, что модуль держит: элемент, заходящий за карниз или угол,
обрезается по стене, целиком срезанный идёт в счёт `cut` описи (`data: Стена до карниза в
данных`); дом с частями разной высоты — не пример, а строка `waiting` описи: модуль держит один
карниз на дом (gf#322). Чего разметчик не размечает (веранда, ступени), он перечисляет в `cut`.

Отделка (gf#245): цоколь — зона от земли до чистого пола (`plinth`) материалом `plinth_material`,
основная — от цоколя до карниза, вторая отделка (акцент, пояс) — прямоугольниками стороны; карниз —
элемент `cornice` стороны рамкой с листа, материалом `trim_material`. Чего на листе нет (цоколя под
обшивкой, карниза на щипцовой стене), разметчик перечисляет в `absent`.
Подоконник, ставни, наличник и козырёк модель шага 4 пишет признаком своего проёма (gf#212): их
связь с проёмом — родитель. Где разметчик родителя не указал, он ставится по месту (`_linked`); вид
этих элементов у дома — по умолчанию из настроек, для тех, что у дома есть.
"""

import math
import tomllib
from collections import Counter
from enum import StrEnum
from pathlib import Path

import numpy
from pydantic import Field, ValidationError

from genfacade import derive, roof
from genfacade.config import Config, Manual
from genfacade.datasets import rect_house, store
from genfacade.schema import (
    EPS,
    BuildingType,
    Element,
    ElementClass,
    FacadeSheet,
    HouseSpec,
    HouseTrim,
    Material,
    MaterialZone,
    Model,
    OpeningVariant,
    PaletteRole,
    Roof,
    RoofKind,
    Sample,
    Source,
    Split,
    Trim,
    ZoneRole,
)
from genfacade.validate import errors, validate


class Unit(StrEnum):
    """Единица отметок листа: американские листы — в футах, российские (gf#328) — в метрах."""

    FT = "ft"
    M = "m"


M_PER_UNIT = {Unit.FT: 0.3048, Unit.M: 1.0}  # международный фут — определение единицы, не настройка

FIRST_NORMAL = (0.0, 1.0)  # сторона входа смотрит в +y плана (rect_house.NORMALS[0])


class BadMarkup(Exception):
    """Разметка не собирается в дом: пример не пишется, причина — в опись."""


class BadContour(BadMarkup):
    """Стороны разметки не складываются в замкнутый ортогональный контур по часовой."""


class Unsupported(Exception):
    """Разметка верна, но такого дома модуль пока не держит: пример не пишется, дом — в `waiting`
    описи с задачей, которая его включит."""


class Mark(Model):
    """Элемент на листе: прямоугольник x0, верх, x1, низ в pt."""

    cls: ElementClass
    box: tuple[float, float, float, float]
    variant: OpeningVariant | None = None
    parent: int | None = None  # номер окна в списке стороны: у ставен, подоконника


class ZoneMark(Model):
    """Вторая отделка на листе: акцент или пояс, прямоугольник x0, верх, x1, низ в pt."""

    role: ZoneRole
    material: str        # вид из library.toml: у дома один вид второй отделки (палитра)
    box: tuple[float, float, float, float]


class EavesMark(Model):
    """Участок карниза на виде: от x0 до x1 и отметка карниза y (верх стены под свесом) в pt,
    этажей под ним."""

    x: tuple[float, float]
    y: float
    floors: int = Field(ge=1)


Point = tuple[float, float]


class Elevation(Model):
    view: str            # подпись вида на листе: по ней разметку сверяют с PDF
    page: int = Field(ge=1)
    wall: tuple[float, float]  # левый и правый край стены, pt
    floor: float         # отметка чистого пола первого этажа, pt
    elements: list[Mark] = []
    zones: list[ZoneMark] = []
    inner_corner: bool = False  # угол после этой стороны — внутренний (Г-, Т-контур, gf#199)
    pt_per_unit: float | None = Field(default=None, gt=0)  # масштаб вида, если не как у дома
    # Запись чертежа выше карниза и по участкам (gf#323): пусто — стена прямоугольником до карниза
    # дома. Сборщик читает участки карниза; силуэт и крыша на виде — для сверки, крыша дома — в
    # полях Markup (gf#336).
    outline: list[Point] = []      # силуэт стены в pt без свесов крыши: фронтон, ступень
    eaves: list[EavesMark] = []
    roof: list[list[Point]] = []   # крыша на виде — многоугольники в pt


class Markup(Model):
    id: str
    pdf: str             # имя листа в pdf/ рядом с разметкой
    roof: str            # исходное описание крыши — в опись; вид, уклон и свес — полями ниже
    roof_kind: RoofKind  # вид крыши дома в параметрах (gf#336): ближайший из строящихся модулем
    pitch_deg: float = Field(ge=0, lt=90)  # уклон ската; у плоской 0 (проверяет `Roof`)
    overhang_m: float = Field(ge=0)        # свес за стену по горизонтали
    unit: Unit           # единица отметок и масштаба
    pt_per_unit: float = Field(gt=0)
    material: str        # вид основной отделки из library.toml
    plinth: float = Field(ge=0)       # чистый пол над землёй
    floor_heights: list[float]        # этажи от чистого пола до карниза
    plinth_material: str | None = None  # вид отделки цоколя; None — цоколя на листе нет (absent)
    trim_material: str | None = None    # вид карниза — элементов `cornice` сторон
    absent: list[str] = []  # чего нет в источнике: «west: карниза нет — щипцовая стена»
    cut: list[str] = []  # срезанное разметчиком: что и с какой стороны
    # Где крыша дома в параметрах не совпадает с листом (gf#336): вид, которого модуль не строит
    # (гамбрел, бабочка, составная), или конёк поперёк правила модуля. Дом остаётся в тесте.
    roof_gaps: list[str] = []
    sides: list[Elevation]

    def scale(self, e: Elevation) -> float:
        """pt на единицу вида: свой у стороны, если её вид начерчен в другом масштабе (gf#323)."""
        return e.pt_per_unit or self.pt_per_unit

    @property
    def m_per_unit(self) -> float:
        return M_PER_UNIT[self.unit]


def read(path: Path) -> Markup:
    return Markup.model_validate(tomllib.loads(path.read_text()))


def ids(source: str, rules: Manual) -> set[str]:
    """Дома источника — по разметкам его папки `markup/<источник>/`, а не по виду имени."""
    return {read(p).id for p in (rules.paths.markup_dir / source).glob("*.toml")}


def house(m: Markup, cfg: Manual) -> tuple[Sample, int]:
    """Пример дома и сколько элементов обрезано целиком (за карнизом или углом)."""
    _one_eaves(m, cfg)
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
    facades = [f.model_copy(update={"zones": _zones(e, m, spec, f.side.length_m)})
               for f, e in zip(sheet.facades, m.sides, strict=True)]
    sheet = sheet.model_copy(update={"facades": facades})
    sheet, bare = _no_eaves(sheet)
    return (Sample(id=m.id, source=Source.MANUAL, split=Split.TEST, plan=plan, sheet=sheet),
            dropped + bare)


def _no_eaves(sheet: FacadeSheet) -> tuple[FacadeSheet, int]:
    """Карниз разметки — только на стенах с краем ската (`facade: Карниз под скатом`): полосу на
    щипцовой стене разметчик снимает с листа (фриз у конька), а модуль карниза там не строит.
    Сколько карнизов снято — в счёт срезанного."""
    eaves, facades, bare = roof.eave_walls(sheet), [], 0
    for k, f in enumerate(sheet.facades):
        keep = [x for x in f.elements if not (x.cls is ElementClass.CORNICE and k not in eaves)]
        bare += len(f.elements) - len(keep)
        facades.append(f.model_copy(update={"elements": keep}))
    return sheet.model_copy(update={"facades": facades}), bare


def _one_eaves(m: Markup, cfg: Manual) -> None:
    """Участки карниза — на стене своей стороны; у всех этажность и отметка дома, иначе у дома
    части разной высоты, а модуль держит один карниз на дом (`facade: Общие параметры дома`)."""
    floors = len(m.floor_heights)
    for e in m.sides:
        tol = cfg.length_tol_m / m.m_per_unit * m.scale(e)
        line = e.floor - sum(m.floor_heights) * m.scale(e)
        for s in e.eaves:
            if s.x[0] < e.wall[0] - tol or s.x[1] > e.wall[1] + tol:
                raise BadMarkup(f"{m.id}: {e.view}: участок карниза за краем стены")
            off = abs(s.y - line) / m.scale(e) * m.m_per_unit
            if s.floors != floors or off > cfg.eaves_tol_m:
                raise Unsupported(f"{m.id}: части разной высоты — {e.view}: карниз над {s.floors} "
                                  f"эт., {off:.2f} м от карниза дома; модуль держит один (gf#322)")


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
    lengths = [(e.wall[1] - e.wall[0]) / m.scale(e) * m.m_per_unit for e in m.sides]
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
    plinth, heights = m.plinth * m.m_per_unit, [h * m.m_per_unit for h in m.floor_heights]
    return HouseSpec(building_type=BuildingType.COTTAGE, floors=len(heights),
                     floor_heights_m=heights, plinth_m=plinth, eaves_m=plinth + sum(heights),
                     roof=Roof(kind=m.roof_kind, pitch_deg=m.pitch_deg, overhang_m=m.overhang_m),
                     materials=_palette(m))


def _palette(m: Markup) -> list[Material]:
    """Палитра дома по разметке: основная, цоколь, карниз и вторая отделка — те, что на листе."""
    second = {z.material for e in m.sides for z in e.zones}
    if len(second) > 1:  # у палитры одна роль второй отделки (`PaletteRole.ACCENT`)
        raise BadMarkup(f"{m.id}: видов второй отделки {len(second)} — у палитры один")
    kinds = {PaletteRole.MAIN: m.material, PaletteRole.ACCENT: next(iter(second), None),
             PaletteRole.PLINTH: m.plinth_material if m.plinth > 0 else None,
             PaletteRole.TRIM: m.trim_material}
    return [Material(id=role, kind=kind) for role, kind in kinds.items() if kind is not None]


def _metres(box: tuple[float, float, float, float], e: Elevation, m: Markup,
            spec: HouseSpec) -> tuple[float, float, float, float]:
    """Прямоугольник листа в pt (x вправо, y вниз) → x0, y0, x1, y1 стены: x от левого края,
    y от земли, метры."""
    x0, top, x1, bottom = (v / m.scale(e) * m.m_per_unit for v in box)
    left, floor = (v / m.scale(e) * m.m_per_unit for v in (e.wall[0], e.floor))
    return x0 - left, spec.plinth_m + floor - bottom, x1 - left, spec.plinth_m + floor - top


def _side_elements(e: Elevation, m: Markup, spec: HouseSpec) -> list[Element]:
    """Прямоугольники листа → элементы стены; карниз — материалом карниза дома."""
    out = []
    for n, mark in enumerate(e.elements):
        x0, y0, x1, y1 = _metres(mark.box, e, m, spec)
        trim = mark.cls is ElementClass.CORNICE and m.trim_material is not None
        out.append(Element(id=f"e{n}", cls=mark.cls, x_m=x0, y_m=y0, w_m=x1 - x0, h_m=y1 - y0,
                           variant=mark.variant, material=PaletteRole.TRIM if trim else None,
                           parent=None if mark.parent is None else f"e{mark.parent}",
                           floor=rect_house.floor_of((y0 + y1) / 2, spec)))
    return out


def _zones(e: Elevation, m: Markup, spec: HouseSpec, length: float) -> list[MaterialZone]:
    """Зоны стены: цоколь от земли до чистого пола, основная — от него до карниза, вторая
    отделка с листа — обрезанной по стене, как в синтетике (`synthetic.zones`)."""
    zone, eaves = MaterialZone.rect, spec.eaves_m
    plinth = spec.plinth_m if m.plinth_material is not None else 0.0
    out = [zone(ZoneRole.PLINTH, PaletteRole.PLINTH, (0.0, 0.0, length, plinth))] if plinth else []
    out.append(zone(ZoneRole.MAIN, PaletteRole.MAIN, (0.0, plinth, length, eaves)))
    for z in e.zones:
        x0, y0, x1, y1 = _metres(z.box, e, m, spec)
        box = (max(x0, 0.0), max(y0, 0.0), min(x1, length), min(y1, eaves))
        if box[2] > box[0] + EPS and box[3] > box[1] + EPS:
            out.append(zone(z.role, PaletteRole.ACCENT, box))
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
    """Все разметки папки → примеры и опись: срезанное, исходные крыши, виды крыш и расхождения
    с листом, ошибки валидатора."""
    rules, root = cfg.data.manual, cfg.data.paths.samples_dir
    # Источник целиком — производное разметки: удалённая разметка не должна оставить пример.
    for old in store.ids(root, Source.MANUAL):
        store.path(root, Source.MANUAL, old).unlink()
    rejected, waiting, cut, roofs, absent, invalid = {}, {}, {}, {}, {}, Counter()
    kinds, gaps = {}, {}
    for path in sorted(rules.paths.markup_dir.glob("*/*.toml")):
        try:  # разметка, которая не читается, — отказ этого дома, а не всей сборки (C10)
            m = read(path)
        except (tomllib.TOMLDecodeError, ValidationError) as e:
            rejected[path.stem] = f"разметка не читается: {e}"
            continue
        try:
            sample, dropped = house(m, rules)
        except BadMarkup as e:
            rejected[m.id] = str(e)
            continue
        except Unsupported as e:
            waiting[m.id] = str(e)
            continue
        cut[m.id], roofs[m.id], absent[m.id] = len(m.cut) + dropped, m.roof, m.absent
        kinds[m.id], gaps[m.id] = m.roof_kind, m.roof_gaps
        invalid.update(v.rule for v in errors(validate(sample.sheet, cfg.checks)))
        store.write(sample, root)
    return store.write_manifest(root, Source.MANUAL, {
        "rejected": rejected, "waiting": waiting, "cut": cut, "roofs": roofs, "absent": absent,
        "roof_kinds": kinds, "roof_gaps": {k: v for k, v in gaps.items() if v},
        "invalid": dict(invalid)})
