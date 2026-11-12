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
карниз. Куда спускается скат — `roof_down`, номер стороны; своя крыша части — `part_roofs`:
часть под отрезком x вида стороны, вид, уклон и сторона низа ската (gf#431).
Сборщик берёт то, что модуль держит: окно во фронтоне — целиком в стене с фронтоном,
какой её строит модуль по крыше дома (`roof.gables`), — остаётся окном этажа под скатом (gf#321),
его выводимые элементы в стене — с ним; другой элемент, заходящий за карниз или угол,
обрезается по стене, целиком срезанный идёт в счёт `cut` описи (`data: Стена до карниза в
данных`); дом, чьи участки карниза не ложатся на части, — не пример, а строка `waiting` описи
(gf#322): отметка крыши не карниз (`_bare`), ступень режет крыло (`_stepped`, gf#422).
Чего разметчик не размечает (веранда, ступени), он перечисляет в `cut`.

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
from typing import NamedTuple

import numpy
import shapely
from pydantic import Field, ValidationError, model_validator

from genfacade import derive, parts, roof, roof_items, window_shape
from genfacade.config import Config, Manual
from genfacade.datasets import rect_house, store
from genfacade.plan.wings import candidates, edge_runs
from genfacade.schema import (
    EPS,
    BuildingType,
    Element,
    ElementClass,
    FacadeSheet,
    Facing,
    HouseSpec,
    HouseTrim,
    Material,
    MaterialZone,
    Model,
    OpeningVariant,
    PaletteRole,
    Plan,
    Polygon,
    Rect,
    Roof,
    RoofKind,
    Sample,
    Source,
    Split,
    Trim,
    VariantKind,
    WallGable,
    WallRun,
    ZoneRole,
)
from genfacade.unfold import unfold
from genfacade.validate import errors, validate


class Unit(StrEnum):
    """Единица отметок листа: американские листы — в футах, российские (gf#328) — в метрах."""

    FT = "ft"
    M = "m"


class OverhangBy(StrEnum):
    """Откуда свес разметки (gf#451): с чертежа или по умолчанию вида крыши."""

    DRAWING = "drawing"  # снят с чертежа
    DEFAULT = "default"  # на чертеже не виден — по умолчанию


M_PER_UNIT = {Unit.FT: 0.3048, Unit.M: 1.0}  # международный фут — определение единицы, не настройка

# Что бывает во фронтоне (gf#321): окно и выводимые элементы окна; дверь и прочее — срезаются.
GABLE_CLASSES = frozenset({ElementClass.WINDOW, *(derive.DERIVED[t] for t in derive.DERIVED
                                                   if derive.OWNER[t] is ElementClass.WINDOW)})

# Крыши, у которых карниз дома — низкий край, а отметка выше — край ската или надстройка (gf#422).
LOW_EDGE_ROOFS = frozenset({RoofKind.SHED, RoofKind.FLAT})

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


class PartRoofMark(Model):
    """Своя крыша части дома (gf#431), как её видно на фасаде: часть — та, чей участок стороны
    `side` лежит под серединой отрезка x (pt вида); `down` — номер стороны, к которой спускается
    скат (у односкатной — низ, у двускатной — одна из карнизных стен)."""

    side: int = Field(ge=0)
    x: tuple[float, float]
    kind: RoofKind
    pitch_deg: float = Field(ge=0, lt=90)
    down: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check(self) -> "PartRoofMark":
        _checked(self.kind, self.pitch_deg, self.down)
        return self


class ChimneyMark(Model):
    """Дымовая труба с чертежа (gf#454): центр трубы на виде стороны `side` в x pt — по нему
    сборщик находит место на коньке главной части (`HouseSpec.chimney`)."""

    side: int = Field(ge=0)
    x: float


def _checked(kind: RoofKind, pitch: float, down: int | None) -> None:
    """Вид, уклон и направление крыши разметки сходятся (`Roof`): ошибка — при чтении файла."""
    Roof(kind=kind, pitch_deg=pitch, down_to=None if down is None else Facing.X_PLUS)


class Markup(Model):
    id: str
    pdf: str             # имя листа в pdf/ рядом с разметкой
    roof: str            # исходное описание крыши — в опись; вид, уклон и свес — полями ниже
    roof_kind: RoofKind  # вид крыши дома в параметрах (gf#336): ближайший из строящихся модулем
    pitch_deg: float = Field(ge=0, lt=90)  # уклон ската; у плоской 0 (проверяет `Roof`)
    overhang_m: float = Field(ge=0)        # свес карнизный: за стену со скатом
    # Свес фронтонный — за стену без ската; нет — равен карнизному (gf#451).
    gable_overhang_m: float | None = Field(default=None, ge=0)
    overhang_by: OverhangBy = OverhangBy.DEFAULT  # откуда свесы: с чертежа или по умолчанию
    # Номер стороны, к которой спускается скат крыши дома (`facade: Направление ската`, gf#431);
    # пусто — правило вида: двускатная — карнизы на длинных стенах, односкатная — низ у входа.
    roof_down: int | None = Field(default=None, ge=0)
    part_roofs: list[PartRoofMark] = []  # свои крыши частей; у остальных — крыша дома
    chimney: ChimneyMark | None = None  # дымовая труба на чертеже (gf#454); нет — трубы нет
    gutters: bool = False  # водосток на чертеже (gf#454)
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

    @model_validator(mode="after")
    def _check_roof(self) -> "Markup":
        _checked(self.roof_kind, self.pitch_deg, self.roof_down)
        return self

    def scale(self, e: Elevation) -> float:
        """pt на единицу вида: свой у стороны, если её вид начерчен в другом масштабе (gf#323)."""
        return e.pt_per_unit or self.pt_per_unit

    @property
    def m_per_unit(self) -> float:
        return M_PER_UNIT[self.unit]

    def px_per_m(self, e: Elevation) -> float:
        """pt листа на метр вида: единица отметок — фут или метр, вид — свой масштаб."""
        return self.scale(e) / self.m_per_unit

    def ground_y(self, e: Elevation) -> float:
        """Земля на виде, pt: чистый пол плюс цоколь."""
        return e.floor + self.plinth * self.scale(e)

    def tops_y(self, e: Elevation) -> list[float]:
        """Верх каждого этажа на виде, pt, снизу вверх; последний — карниз."""
        y, tops = e.floor, []
        for h in self.floor_heights:
            y -= h * self.scale(e)
            tops.append(y)
        return tops

    def with_ground(self, e: Elevation, y: float) -> "Markup":
        """Разметка с цоколем, при котором земля стоит на виде e в y (обратное `ground_y`)."""
        return self.model_copy(update={"plinth": max(0.0, (y - e.floor) / self.scale(e))})

    def with_top(self, e: Elevation, k: int, y: float) -> "Markup":
        """Разметка с k-м этажом такой высоты, чтобы его верх на виде e стоял в y."""
        below = e.floor if k == 0 else self.tops_y(e)[k - 1]
        heights = list(self.floor_heights)
        heights[k] = max(EPS, (below - y) / self.scale(e))
        return self.model_copy(update={"floor_heights": heights})


def read(path: Path) -> Markup:
    return Markup.model_validate(tomllib.loads(path.read_text()))


def ids(source: str, rules: Manual) -> set[str]:
    """Дома источника — по разметкам его папки `markup/<источник>/`, а не по виду имени."""
    return {read(p).id for p in (rules.paths.markup_dir / source).glob("*.toml")}


def house(m: Markup, cfg: Manual) -> tuple[Sample, int]:
    """Пример дома и сколько элементов обрезано целиком (за карнизом или углом). Отметки разметки
    берутся как есть; не легли на части — без отметок крыши (`_bare`), потом с виртуальными
    крыльями по ступеням (`_stepped`), потом оба (gf#422); первый отказ — причина, если не легло."""
    refusal = None
    for bare, cut in ((False, False), (True, False), (False, True), (True, True)):
        try:
            return _house(_bare(m, cfg) if bare else m, cfg, cut)
        except Unsupported as e:
            refusal = refusal or e
    raise refusal


class _Contour(NamedTuple):
    """Контур дома по разметке: длины, углы и нормали сторон, крылья, этажности частей, участки
    сторон по частям (`runs`, у дома разной высоты) и по крыльям (`spans`), щипцы над стенами."""

    lengths: list[float]
    ring: list[Point]
    normals: list[Point]
    rects: list[Rect]
    found: list[parts.Level]
    runs: list[list[WallRun]]
    spans: list[list[parts.Span]]
    tents: list[WallGable]


def _contour(m: Markup, fp: rect_house.Footprint, cfg: Manual, cut: bool) -> _Contour:
    lengths = [w.length for w in fp.walls]
    ring = [(float(v[0]) + 0.0, float(v[1]) + 0.0) for v in fp.vertices]
    normals = [(float(w.normal[0]), float(w.normal[1])) for w in fp.walls]
    rects, found = _levels(m, ring, lengths, cfg, cut)
    ends = [(ring[k], ring[(k + 1) % len(ring)]) for k in range(len(m.sides))]
    runs = [parts.side_runs(k, lengths[k], *ends[k], rects, found) if found else []
            for k in range(len(m.sides))]
    spans = [parts.side_spans(k, lengths[k], *ends[k], rects) if rects else []
             for k in range(len(m.sides))]
    return _Contour(lengths, ring, normals, rects, found, runs, spans,
                    _wall_gables(m, cfg, bool(rects)))


def _house(m: Markup, cfg: Manual, cut: bool) -> tuple[Sample, int]:
    fp = _outline(m, cfg)
    c = _contour(m, fp, cfg, cut)
    spec = _spec(m)
    spec = spec.model_copy(update={"roof": spec.roof.model_copy(
        update={"down_to": _down(m, m.roof_down, c.normals)})})
    raw = [_side_elements(e, m, spec) for e in m.sides]
    # стороны плана — по проёмам первого этажа, фронтон — по крыше листа без окон выше карниза
    # (они на стороны не влияют): та же зона, что у валидатора и листа (`roof.sheet_gables`)
    first = rect_house.assemble(spec, fp, _laid(raw, [None] * len(raw), c, spec, cfg)[0],
                                Source.MANUAL)
    laid, dropped = _laid(raw, roof.sheet_gables(_parted(*first, m, c)[1]), c, spec, cfg)
    spec = spec.model_copy(update={"trim": _trim([xs for _, xs in laid], cfg.trim)})
    plan, sheet = rect_house.assemble(spec, fp, laid, Source.MANUAL)
    facades = [f.model_copy(update={"zones": _zones(e, m, spec, f.side.length_m, r)})
               for f, e, r in zip(sheet.facades, m.sides, c.runs, strict=True)]
    plan, sheet = _parted(plan, sheet.model_copy(update={"facades": facades}), m, c)
    sheet, bare = _no_eaves(sheet)
    sheet = _roof_items(sheet, m, cfg)
    return (Sample(id=m.id, source=Source.MANUAL, split=Split.TEST, plan=plan, sheet=sheet),
            dropped + bare)


def _roof_items(sheet: FacadeSheet, m: Markup, cfg: Manual) -> FacadeSheet:
    """Труба и водосток разметки в параметрах дома (gf#454): труба — доля конька главной части,
    ближайшая к центру трубы на виде (проекция его точки на конёк, в пределах 0–1: центр за краем
    стены — труба у торца конька). Ошибка разметки: неверная сторона, x дальше края кровли на
    `chimney_beyond_m`, дом без конька."""
    spec = sheet.spec.model_copy(update={"gutters": m.gutters})
    mark = m.chimney
    if mark is None:
        return sheet.model_copy(update={"spec": spec})
    if mark.side >= len(m.sides):
        raise BadMarkup(f"{m.id}: труба на стороне {mark.side}, а сторон {len(m.sides)}")
    e, length = m.sides[mark.side], sheet.facades[mark.side].side.length_m
    x = (mark.x - e.wall[0]) / m.px_per_m(e)
    reach = sheet.spec.roof.reach + cfg.chimney_beyond_m  # труба снаружи у щипца — у торца конька
    if not -reach <= x <= length + reach:
        raise BadMarkup(f"{m.id}: {e.view}: труба на x {mark.x} — вне кровли")
    house = roof.roofs(sheet)
    found = None if house is None else roof_items.ridge(house.parts[roof.own_parts(house)[0]])
    if house is None or found is None:
        raise BadMarkup(f"{m.id}: труба у дома без конька")
    (ax, ay), (bx, by), _ = found
    left, u, _ = roof.axis(house.corners, mark.side)
    px, py = left[0] + u[0] * x - ax, left[1] + u[1] * x - ay
    run = (bx - ax) ** 2 + (by - ay) ** 2
    at = min(1.0, max(0.0, (px * (bx - ax) + py * (by - ay)) / run)) if run > EPS else 0.0
    return sheet.model_copy(update={"spec": spec.model_copy(update={"chimney": at})})


def _parted(plan: Plan, sheet: FacadeSheet, m: Markup, c: _Contour) -> tuple[Plan, FacadeSheet]:
    """План и лист с участками сторон, щипцами над стенами и, у дома из крыльев, крыльями и крышами
    частей (силуэт ступенями — только при разных высотах)."""
    facades = [f.model_copy(update={"runs": r}) for f, r in zip(sheet.facades, c.runs, strict=True)]
    sheet = sheet.model_copy(update={"facades": facades, "wall_gables": c.tents})
    if not c.rects:
        if m.part_roofs:
            raise BadMarkup(f"{m.id}: крыши частей у дома без частей")
        return plan, sheet
    plan = plan.model_copy(update={"wings": c.rects})
    return plan, roof.with_covered(unfold(sheet.model_copy(update={
        "wings": parts.sheet_wings(plan),
        "roofs": _part_roofs(m, c.spans, sheet.spec, c.normals)})))


def _laid(raw: list[list[Element]], gables: list[Polygon | None], c: _Contour, spec: HouseSpec,
          cfg: Manual) -> tuple[list[tuple[int, list[Element]]], int]:
    """Элементы сторон, которые модуль держит, и сколько срезано целиком: во фронтоне — как есть
    (`_in_gable`), остальное — по стене до карниза (`_clipped`); подоконник или ставня срезанного
    окна (поперечный щипец над карнизной стеной) — с ним."""
    laid, dropped = [], 0
    for k, (elements, above) in enumerate(zip(raw, gables, strict=True)):
        kept = [x for x in (_in_gable(x, c.lengths[k], above, spec, cfg)
                            or _clipped(x, c.lengths[k], spec, cfg, c.runs[k]) for x in elements)
                if x]
        ids = {x.id for x in kept}  # выводимый элемент срезанного окна срезан с ним
        kept = [x for x in kept if x.parent is None or x.parent in ids]
        dropped += len(elements) - len(kept)
        laid.append((k, _linked(kept, cfg.link_tol_m)))
    return laid, dropped


def _in_gable(x: Element, length: float, above: Polygon | None, spec: HouseSpec,
              cfg: Manual) -> Element | None:
    """Окно и его выводимые элементы над карнизом, целиком в стене с фронтоном (gf#321), — этажа
    под скатом; иначе None (решает `_clipped`)."""
    if above is None or x.y_m + x.h_m <= spec.eaves_m + EPS or x.cls not in GABLE_CLASSES:
        return None
    wall = roof.wall_shape(length, spec.eaves_m, above).buffer(cfg.gable_tol_m)
    box = shapely.box(x.x_m, x.y_m, x.x_m + x.w_m, x.y_m + x.h_m)
    if window_shape.kind(x) is VariantKind.SLOPE:  # рамка по скату — контур срезан скатом (gf#319)
        if wall.intersection(box).area < cfg.inside_share * box.area:
            return None
    elif not wall.contains(box):
        return None
    return x.model_copy(update={"floor": spec.floors + 1})


def _no_eaves(sheet: FacadeSheet) -> tuple[FacadeSheet, int]:
    """Карниз разметки — только на стенах с краем ската (`facade: Карниз под скатом`): полосу на
    щипцовой стене разметчик снимает с листа (фриз у конька), а модуль карниза там не строит.
    Сколько карнизов снято — в счёт срезанного."""
    eaves, facades, bare = roof.eave_walls(sheet), [], 0
    for k, f in enumerate(sheet.facades):
        keep = [x for x in f.elements if not (x.cls is ElementClass.CORNICE and k not in eaves)]
        bare += len(f.elements) - len(keep)
        gaps = [(g.x0_m, g.x1_m) for g in sheet.wall_gables if g.side == k]
        facades.append(f.model_copy(update={"elements": _cornice_gaps(keep, gaps)}))
    return sheet.model_copy(update={"facades": facades}), bare


def _cornice_gaps(elements: list[Element], gaps: list[tuple[float, float]]) -> list[Element]:
    """Карниз прерывается под щипцом над стеной (`facade: Щипец над карнизной стеной`): перед
    стеной видна кровля щипца, и окно в нём стоит на уровне карниза. Кусок — под тем же классом,
    с id от id карниза; уже не шире допуска — снимается."""
    out = []
    for x in elements:
        if x.cls is not ElementClass.CORNICE or not gaps:
            out.append(x)
            continue
        edges = [x.x_m, *(v for g in sorted(gaps) for v in g), x.x_m + x.w_m]
        pieces = [(a, b) for a, b in zip(edges[::2], edges[1::2], strict=True) if b - a > EPS]
        out += [x.model_copy(update={"id": x.id if i == 0 else f"{x.id}_{i}",
                                     "x_m": a, "w_m": b - a}) for i, (a, b) in enumerate(pieces)]
    return out


def _bare(m: Markup, cfg: Manual) -> Markup:
    """Разметка без отметок крыши (gf#422): у односкатной и плоской крыши карниз дома — низкий край,
    а отметка выше него (высокий край ската, надстройка или полоса панелей) — не карниз, а крыша:
    высоту стены под ней выводит `roof.above_eaves`, что выше карниза, — в `cut` и `roof_gaps`.
    У других крыш не карниз — отметка выше карниза дома. Этажность не меняется: те же этажи — одна
    высота стены; разметка в файле остаётся записью чертежа целиком (gf#323)."""
    spec = _spec(m)
    levels = [lv for e in m.sides for _, lv in _raw(m, e, cfg) if lv.floors == spec.floors]
    base = spec.eaves_m
    if m.roof_kind in LOW_EDGE_ROOFS and levels:
        base = min(lv.eaves_m for lv in levels)
    sides = [e.model_copy(update={"eaves": [s for s in e.eaves
                                            if not _is_roof(m, e, s, base, cfg)]})
             for e in m.sides]
    heights = list(m.floor_heights)
    heights[-1] += (base - spec.eaves_m) / m.m_per_unit
    return m.model_copy(update={"sides": sides, "floor_heights": heights})


def _is_roof(m: Markup, e: Elevation, s: EavesMark, base: float, cfg: Manual) -> bool:
    """Участок карниза — край крыши, не стена: тех же этажей, что дом, и выше его карниза."""
    eaves = m.plinth * m.m_per_unit + (e.floor - s.y) * m.m_per_unit / m.scale(e)
    return s.floors == len(m.floor_heights) and eaves > base + cfg.eaves_tol_m


def _levels(m: Markup, ring: list[Point], lengths: list[float], cfg: Manual, cut: bool
            ) -> tuple[list[Rect], list[parts.Level]]:
    """Крылья контура и этажность с карнизом каждого — по участкам карниза разметки; дом без
    ступеней — крылья и пустой список этажностей. Участок стороны лежит на крыле (`edge_runs`), его
    отметку несут участки
    карниза, заходящие на него дальше `length_tol_m`; у крыла все участки одной отметки, иначе
    части не ложатся на крылья (ступень внутри крыла, крыло в две отметки) — `Unsupported`; с `cut`
    крыло перед этим режется по линиям ступени (`_stepped`, gf#422).
    Разбиений контура несколько (`candidates`): берётся первое, на котором отметки ложатся.
    Отметка в пределах `eaves_tol_m` от карниза дома — он сам."""
    base = parts.Level(len(m.floor_heights), _spec(m).eaves_m)
    refusal = None
    options = candidates(ring) or [[]]
    for rects in options:
        try:
            if cut:
                rects = _stepped(m, ring, lengths, cfg, rects, base)
            return _levels_on(m, ring, lengths, cfg, rects, base)
        except Unsupported as e:
            refusal = refusal or e  # первый отказ — по разбиению `wings`, его и называем
    raise refusal


def _levels_on(m: Markup, ring: list[Point], lengths: list[float], cfg: Manual,
               rects: list[Rect], base: parts.Level) -> tuple[list[Rect], list[parts.Level]]:
    """Этажность и карниз крыльев одного разбиения контура; не ложатся — `Unsupported`."""
    seen: dict[int, list[parts.Level]] = {}
    for k, e in enumerate(m.sides):
        marks = _marks(m, e, base, cfg)
        for part, t0, t1 in edge_runs(ring[k], ring[(k + 1) % len(ring)], rects) or [
                (0, 0.0, lengths[k])]:
            x0, x1 = lengths[k] - t1, lengths[k] - t0
            found = _distinct([lv for (a, b), lv in marks
                               if min(b, x1) - max(a, x0) > cfg.length_tol_m], cfg)
            if len(found) > 1:
                raise Unsupported(f"{m.id}: части разной высоты — {e.view}: на одном участке "
                                  f"стены {len(found)} отметок карниза; модуль держит одну на "
                                  f"крыло (gf#322)")
            seen.setdefault(part, []).extend(found)
    levels = [_one_level(m, seen.get(k, []), base, cfg) for k in range(len(rects) or 1)]
    if not rects and levels != [base]:
        raise Unsupported(f"{m.id}: части разной высоты — ступень внутри прямоугольного контура: "
                          f"карниз над {levels[0].floors} эт., {levels[0].eaves_m:.2f} м; "
                          f"крыльев в контуре нет (gf#322)")
    return (rects, levels) if len({lv.eaves_m for lv in levels}) > 1 else (rects, [])


def _distinct(levels: list[parts.Level], cfg: Manual) -> list[parts.Level]:
    """Отметки без повторов с допуском `eaves_tol_m`: 3,14 и 3,15 м — одна."""
    out: list[parts.Level] = []
    for lv in levels:
        if not any(_same(lv, o, cfg) for o in out):
            out.append(lv)
    return out


def _stepped(m: Markup, ring: list[Point], lengths: list[float], cfg: Manual,
             rects: list[Rect], base: parts.Level) -> list[Rect]:
    """Крылья по ступеням карниза (gf#422): крыло, на грани которого карниз меняется, режется
    линией ступени — виртуальные крылья листа. Линия ступени идёт от места на стороне, где отметка
    карниза сменилась, поперёк стороны через всё крыло; линии одного крыла в пределах
    `length_tol_m` — одна (у marilyn 4,79 и 4,88 м). Без ступеней — `Unsupported`."""
    wings = rects or [_box(ring)]
    steps: list[list[tuple[bool, float]]] = [[] for _ in wings]  # (линия x = c?, c) на крыло
    for k, e in enumerate(m.sides):
        a, b = ring[k], ring[(k + 1) % len(ring)]
        along = (b[0] - a[0], b[1] - a[1])
        horizontal = abs(along[0]) > abs(along[1])  # сторона вдоль x → линия ступени x = c
        marks = _marks(m, e, base, cfg)
        for at in _jumps(marks, base, lengths[k], cfg):
            t = lengths[k] - at
            point = (a[0] + along[0] / lengths[k] * t, a[1] + along[1] / lengths[k] * t)
            for j, w in enumerate(wings):
                on = min(abs(point[1] - w.y0_m), abs(point[1] - w.y1_m)) if horizontal else min(
                    abs(point[0] - w.x0_m), abs(point[0] - w.x1_m))
                if on <= cfg.length_tol_m:
                    steps[j].append((horizontal, point[0] if horizontal else point[1]))
    out: list[Rect] = []
    for w, lines in zip(wings, steps, strict=True):
        out.extend(_cut(w, lines, cfg))
    if len(out) == len(wings):
        raise Unsupported(f"{m.id}: части разной высоты — линий ступени карниза нет (gf#422)")
    return out


def _box(ring: list[Point]) -> Rect:
    xs, ys = [v[0] for v in ring], [v[1] for v in ring]
    return Rect(x0_m=min(xs), y0_m=min(ys), x1_m=max(xs), y1_m=max(ys))


def _jumps(marks: list[tuple[Point, parts.Level]], base: parts.Level, length: float, cfg: Manual
           ) -> list[float]:
    """Где вдоль стороны (x стены) карниз меняется — внутри стороны, не у углов; без отметки —
    карниз    дома. Отметка сменилась, если до и после точки (на `length_tol_m`) уровни разные."""
    def level(x: float) -> parts.Level:
        return next((lv for (a, b), lv in marks if a <= x <= b), base)

    cands = {v for (a, b), _ in marks for v in (a, b)
             if cfg.length_tol_m < v < length - cfg.length_tol_m}
    return sorted(c for c in cands if not _same(level(c - cfg.length_tol_m),
                                                level(c + cfg.length_tol_m), cfg))


def _cut(w: Rect, lines: list[tuple[bool, float]], cfg: Manual) -> list[Rect]:
    """Крыло w по линиям ступени: x = c (True) и y = c (False); близкие — одна, у края — нет."""
    pieces = [w]
    for vertical in (True, False):
        lo, hi = (w.x0_m, w.x1_m) if vertical else (w.y0_m, w.y1_m)
        cs = sorted(c for v, c in lines if v == vertical and lo + cfg.length_tol_m < c
                    < hi - cfg.length_tol_m)
        groups: list[list[float]] = []
        for c in cs:
            if groups and c - groups[-1][-1] <= cfg.length_tol_m:
                groups[-1].append(c)
            else:
                groups.append([c])
        edges = [lo, *(round(sum(g) / len(g), parts.SNAP) + 0.0 for g in groups), hi]
        pieces = [Rect(x0_m=a, y0_m=p.y0_m, x1_m=b, y1_m=p.y1_m) if vertical
                  else Rect(x0_m=p.x0_m, y0_m=a, x1_m=p.x1_m, y1_m=b)
                  for p in pieces for a, b in zip(edges[:-1], edges[1:], strict=True)]
    return pieces


def _raw(m: Markup, e: Elevation, cfg: Manual) -> list[tuple[Point, parts.Level]]:
    """Участки карниза стороны в метрах стены: (x0, x1) и этажность с отметкой, как в разметке."""
    unit, out = m.m_per_unit / m.scale(e), []
    for s in e.eaves:
        tol = cfg.length_tol_m / unit
        if s.x[0] < e.wall[0] - tol or s.x[1] > e.wall[1] + tol:
            raise BadMarkup(f"{m.id}: {e.view}: участок карниза за краем стены")
        out.append((((s.x[0] - e.wall[0]) * unit, (s.x[1] - e.wall[0]) * unit),
                    parts.Level(s.floors, m.plinth * m.m_per_unit + (e.floor - s.y) * unit)))
    return out


def _marks(m: Markup, e: Elevation, base: parts.Level, cfg: Manual
           ) -> list[tuple[Point, parts.Level]]:
    """Участки карниза стороны в метрах стены: (x0, x1) и этажность с отметкой; отметка около
    карниза дома — он сам."""
    return [(span, base if _same(level, base, cfg) else level)
            for span, level in _raw(m, e, cfg)]


def _same(a: parts.Level, b: parts.Level, cfg: Manual) -> bool:
    return a.floors == b.floors and abs(a.eaves_m - b.eaves_m) <= cfg.eaves_tol_m


def _one_level(m: Markup, seen: list[parts.Level], base: parts.Level, cfg: Manual
               ) -> parts.Level:
    """Этажность и карниз крыла по его участкам: без разметки — дом; две разные — отказ."""
    if not seen:
        return base
    first = seen[0]
    if any(not _same(lv, first, cfg) for lv in seen):
        raise Unsupported(f"{m.id}: части разной высоты — на одном крыле отметки карниза "
                          f"{sorted({(lv.floors, round(lv.eaves_m, 2)) for lv in seen})}; "
                          f"модуль держит одну на крыло (gf#322)")
    return first


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
                     roof=Roof(kind=m.roof_kind, pitch_deg=m.pitch_deg, overhang_m=m.overhang_m,
                               gable_overhang_m=m.gable_overhang_m),
                     materials=_palette(m))


def _down(m: Markup, down: int | None, normals: list[Point]) -> Facing | None:
    """Куда спускается скат: сторона плана по наружной нормали стороны down."""
    if down is None:
        return None
    if down >= len(normals):
        raise BadMarkup(f"{m.id}: скат к стороне {down}, а сторон {len(normals)}")
    return Facing.of(normals[down])


def _part_roofs(m: Markup, spans: list[list[parts.Span]], spec: HouseSpec,
                normals: list[Point]) -> list[Roof]:
    """Крыша каждой части: своя из разметки (`part_roofs`) или крыша дома. Часть — та, чей участок
    стороны (крыло на ней) под серединой отрезка разметки."""
    count = 1 + max(r.part for side in spans for r in side)
    out: list[Roof | None] = [None] * count
    for mark in m.part_roofs:
        if mark.side >= len(m.sides):
            raise BadMarkup(f"{m.id}: крыша части на стороне {mark.side}, а сторон {len(m.sides)}")
        e = m.sides[mark.side]
        mid = ((mark.x[0] + mark.x[1]) / 2 - e.wall[0]) * m.m_per_unit / m.scale(e)
        part = next((r.part for r in spans[mark.side] if r.x0 <= mid <= r.x1), None)
        if part is None or out[part] is not None:
            raise BadMarkup(f"{m.id}: {e.view}: крыша части на x {mark.x} — "
                            f"{'нет участка' if part is None else 'у части уже есть крыша'}")
        out[part] = spec.roof.model_copy(update={  # вид и направление проверены при чтении
            "kind": mark.kind, "pitch_deg": mark.pitch_deg,
            "down_to": _down(m, mark.down, normals)})
    return [r or spec.roof for r in out] if m.part_roofs else []


def _wall_gables(m: Markup, cfg: Manual, winged: bool) -> list[WallGable]:
    """Щипцы над карнизными стенами по силуэту стены (gf#431): треугольник, что поднимается от
    карниза и возвращается к нему внутри стены. У края стены — фронтон или ступень части, их
    строит крыша части; вертикальный подъём от карниза — стена более высокой части. У дома без
    крыльев части нет, и треугольник от угла стены — щипец над стеной (georgia)."""
    return [g for k, e in enumerate(m.sides) for g in _tents(m, k, e, cfg, winged)]


def _tents(m: Markup, k: int, e: Elevation, cfg: Manual, winged: bool) -> list[WallGable]:
    """Треугольники над карнизом на силуэте стороны k: уклон — по высоте вершины над карнизом и
    половине основания (масштаб вида один по обеим осям)."""
    scale = m.px_per_m(e)
    tol, edge, ring, out = cfg.eaves_tol_m * scale, cfg.length_tol_m * scale, e.outline, []
    length = (e.wall[1] - e.wall[0]) / scale
    for i, a in enumerate(ring[:-1]):
        j = next((j for j in range(i + 1, len(ring)) if ring[j][1] >= a[1] - tol), len(ring))
        if j == i + 1 or j == len(ring) or ring[i + 1][0] - a[0] <= edge:
            continue
        b, top = ring[j], min(p[1] for p in ring[i + 1:j])
        if _in_wall(e, a[0], b[0], edge, winged) and abs(b[1] - a[1]) <= tol \
                and abs(a[1] - _eaves_y(m, e, a[0], edge)) <= tol:
            out.append(WallGable(side=k, x0_m=max(0.0, (a[0] - e.wall[0]) / scale),
                                 x1_m=min((b[0] - e.wall[0]) / scale, length),
                                 pitch_deg=math.degrees(math.atan2(a[1] - top, (b[0] - a[0]) / 2))))
    return out


def _in_wall(e: Elevation, x0: float, x1: float, edge: float, winged: bool) -> bool:
    """Основание треугольника [x0, x1] — на стене: оба конца внутри; у дома без крыльев один конец
    может стоять на углу стены, оба на углах — фронтон крыши дома, его строит она."""
    inner = (e.wall[0] + edge < x0) + (x1 < e.wall[1] - edge)
    return inner == 2 or (inner == 1 and not winged)


def _eaves_y(m: Markup, e: Elevation, x: float, tol: float) -> float:
    """Карниз на виде в точке x стены, pt: участка карниза разметки, без него — дома."""
    return next((s.y for s in e.eaves if s.x[0] - tol <= x <= s.x[1] + tol), m.tops_y(e)[-1])


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


def _spans(spec: HouseSpec, length: float, runs: list[WallRun]) -> list[WallRun]:
    """Участки стены: у дома без ступеней — вся стена до карниза дома."""
    return runs or [WallRun(x0_m=0.0, x1_m=length, part=0, floors=spec.floors,
                            eaves_m=spec.eaves_m)]


def _zones(e: Elevation, m: Markup, spec: HouseSpec, length: float, runs: list[WallRun]
           ) -> list[MaterialZone]:
    """Зоны стены: цоколь от земли до чистого пола и основная — от него до карниза, у стены из
    частей (gf#322) — по участку до его карниза; вторая отделка с листа — обрезанной по участку,
    как в синтетике (`synthetic.zones`)."""
    zone, spans = MaterialZone.rect, _spans(spec, length, runs)
    plinth = spec.plinth_m if m.plinth_material is not None else 0.0
    out = []
    for r in spans:
        if plinth:
            out.append(zone(ZoneRole.PLINTH, PaletteRole.PLINTH, (r.x0_m, 0.0, r.x1_m, plinth)))
        out.append(zone(ZoneRole.MAIN, PaletteRole.MAIN, (r.x0_m, plinth, r.x1_m, r.eaves_m)))
    for z in e.zones:
        x0, y0, x1, y1 = _metres(z.box, e, m, spec)
        for r in spans:
            box = (max(x0, r.x0_m), max(y0, 0.0), min(x1, r.x1_m), min(y1, r.eaves_m))
            if box[2] > box[0] + EPS and box[3] > box[1] + EPS:
                out.append(zone(z.role, PaletteRole.ACCENT, box))
    return out


def _clipped(x: Element, length: float, spec: HouseSpec, cfg: Manual,
             runs: list[WallRun]) -> Element | None:
    """Обрезать по стене до карниза её части (у стены из частей — участка, где центр элемента);
    внутри меньше inside_share — элемента нет."""
    spans = _spans(spec, length, runs)
    centre = x.x_m + x.w_m / 2
    r = next((r for r in spans if centre <= r.x1_m + EPS), spans[-1])
    x0, y0 = max(x.x_m, r.x0_m), max(x.y_m, 0.0)
    x1, y1 = min(x.x_m + x.w_m, r.x1_m), min(x.y_m + x.h_m, r.eaves_m)
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
    с листом, окна во фронтоне (gf#321), ошибки валидатора."""
    rules, root = cfg.data.manual, cfg.data.paths.samples_dir
    # Источник целиком — производное разметки: удалённая разметка не должна оставить пример.
    for old in store.ids(root, Source.MANUAL):
        store.path(root, Source.MANUAL, old).unlink()
    rejected, waiting, cut, roofs, absent, invalid = {}, {}, {}, {}, {}, Counter()
    kinds, gaps, gables = {}, {}, {}
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
        gables[m.id] = gable_windows(sample.sheet)
        invalid.update(v.rule for v in errors(validate(sample.sheet, cfg.checks)))
        store.write(sample, root)
    return store.write_manifest(root, Source.MANUAL, {
        "rejected": rejected, "waiting": waiting, "cut": cut, "roofs": roofs, "absent": absent,
        "roof_kinds": kinds, "roof_gaps": {k: v for k, v in gaps.items() if v},
        "gable_windows": {k: v for k, v in gables.items() if v}, "invalid": dict(invalid)})


def gable_windows(sheet: FacadeSheet) -> int:
    """Окон во фронтоне у дома — окон этажа под скатом (gf#321)."""
    return sum(e.cls is ElementClass.WINDOW and roof.under_roof(e, sheet.spec.floors)
               for f in sheet.facades for e in f.elements)
