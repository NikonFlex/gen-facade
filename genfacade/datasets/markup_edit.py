"""Правка разметки со страницы /markup (gf#348): что браузер присылает и как оно ложится в `Markup`.

Браузер двигает рамки и линии в pt листа, а метры, этажи и цоколь считает только этот модуль через
`Markup.ground_y / tops_y / with_ground / with_top` — второго пересчёта метры ↔ пиксели нет
(тот же, что в `tools/markup.py overlay`). Линии земли и этажей приходят pt-отметкой на виде и
пересчитываются в цоколь и высоты этажей дома: значение общее для всех сторон.

Поля дома (`HouseEdit`: крыша, кровля, водосток, обрамление, материалы, цвета ролей палитры, вид
второй отделки) и отметки на видах (трубы, мансардные и слуховые окна, крыльцо под кровлей —
`Edit.chimneys` и так далее; зоны второй отделки — `SideEdit.zones`, gf#470) приходят тем же
запросом и ложатся в `Markup` здесь же; допустимость вида, уклона и ската проверяет сама
`Markup` (`Roof`), виды по каталогам — `check_kinds` и `check_materials`.
"""

from collections.abc import Collection

from pydantic import Field

from genfacade.datasets.manual import (
    ChimneyMark,
    DormerMark,
    Elevation,
    Mark,
    Markup,
    OverhangBy,
    PorchRoofMark,
    SkylightMark,
    TrimMark,
    ZoneMark,
)
from genfacade.schema import EPS, LevelKind, MarkKind, Model, PaletteRole, RoofKind

MARK_ROUND = 1   # знаков после запятой у координат в pt: 0,1 pt листа — меньше пикселя
UNIT_ROUND = 3   # у цоколя и высот этажей в единицах вида: миллиметры при метрах


class SideEdit(Model):
    wall: tuple[float, float]
    pt_per_unit: float = Field(gt=0)   # масштаб вида, pt на единицу отметок
    elements: list[Mark]
    zones: list[ZoneMark] | None = None   # вторая отделка стороны: нет в запросе — не меняется



class LevelEdit(Model):
    side: int = Field(ge=0)
    kind: LevelKind
    index: int = Field(default=0, ge=0)
    y: float


class HouseEdit(Model):
    """Поля дома, которые правит страница: страница присылает их все, как они стоят в полях."""

    roof_kind: RoofKind
    pitch_deg: float
    overhang_m: float
    gable_overhang_m: float | None
    overhang_by: OverhangBy
    roof_down: int | None
    roof_material: str | None
    gutters: bool
    material: str
    plinth_material: str | None
    trim_material: str | None
    trim: TrimMark
    # Цвет `#rrggbb` по роли палитры (пустой словарь — цветов нет) и вид второй отделки: он один,
    # его получают все зоны (gf#470). Нет в запросе — не меняются.
    colors: dict[PaletteRole, str] | None = None
    second_material: str | None = None


class Edit(Model):
    """Правка со страницы. Список отметок, которого нет в запросе, не меняется; пустой — стирает."""

    sides: list[SideEdit]
    levels: list[LevelEdit] = []
    house: HouseEdit | None = None
    chimneys: list[ChimneyMark] | None = None
    skylights: list[SkylightMark] | None = None
    dormers: list[DormerMark] | None = None
    porch_roofs: list[PorchRoofMark] | None = None


MARK_FIELDS = {MarkKind.CHIMNEY: "chimneys", MarkKind.SKYLIGHT: "skylights",
               MarkKind.DORMER: "dormers", MarkKind.PORCH_ROOF: "porch_roofs"}


def _box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Рамка с x0 < x1 и верхом выше низа: тянут за любой угол, и через противоположный."""
    x0, y0, x1, y1 = (round(v, MARK_ROUND) for v in box)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _mark(mark: Mark, count: int) -> Mark:
    """Рамка начисто; родитель, которого нет в списке стороны, — ошибка, а не потерянная связь."""
    if mark.parent is not None and not 0 <= mark.parent < count:
        raise ValueError(f"родитель {mark.parent} — вне списка из {count} элементов")
    return mark.model_copy(update={"box": _box(mark.box)})


def _side(m: Markup, k: int, edit: SideEdit) -> Elevation:
    """Сторона после правки; масштаб записывается стороне, только если он не как у дома."""
    own = None if abs(edit.pt_per_unit - m.pt_per_unit) < EPS else edit.pt_per_unit
    count = len(edit.elements)
    zones = {} if edit.zones is None else {"zones": [
        z.model_copy(update={"box": _box(z.box)}) for z in edit.zones]}
    return m.sides[k].model_copy(update={
        "wall": tuple(round(v, MARK_ROUND) for v in sorted(edit.wall)),
        "pt_per_unit": own,
        "elements": [_mark(x, count) for x in edit.elements], **zones})


def _level(m: Markup, edit: LevelEdit) -> Markup:
    if edit.side >= len(m.sides):
        raise ValueError(f"нет стороны {edit.side}")
    e = m.sides[edit.side]
    if edit.kind is LevelKind.FLOOR:
        sides = list(m.sides)
        sides[edit.side] = e.model_copy(update={"floor": round(edit.y, MARK_ROUND)})
        return m.model_copy(update={"sides": sides})
    if edit.kind is LevelKind.GROUND:
        return m.with_ground(e, edit.y)
    if edit.index >= len(m.floor_heights):
        raise ValueError(f"нет этажа {edit.index}")
    return m.with_top(e, edit.index, edit.y)


# пол раньше земли и этажей: от него считаются обе; этажи — снизу вверх
LEVEL_ORDER = list(LevelKind)


def apply(m: Markup, edit: Edit) -> Markup:
    """Разметка после правки; не складывается (чужое число сторон, родитель вне списка, плохой
    масштаб) — ValueError с причиной."""
    if len(edit.sides) != len(m.sides):
        raise ValueError(f"сторон {len(edit.sides)}, в разметке {len(m.sides)}")
    sides = _second(edit, [_side(m, k, s) for k, s in enumerate(edit.sides)])
    out = m.model_copy(update={"sides": sides, **_house(edit), **_marks(edit, len(sides))})
    ordered = sorted(edit.levels, key=lambda v: (LEVEL_ORDER.index(v.kind), v.index))
    for level in ordered:   # масштабы сторон уже новые: линия ставится туда, куда её отпустили
        out = _level(out, level)
    return round_units(Markup.model_validate(out.model_dump()))


def _second(edit: Edit, sides: list[Elevation]) -> list[Elevation]:
    """Вид второй отделки дома — всем зонам всех сторон: на странице он поле дома, а не зоны."""
    kind = None if edit.house is None else edit.house.second_material
    if kind is None:
        return sides
    return [e.model_copy(update={"zones": [z.model_copy(update={"material": kind})
                                            for z in e.zones]}) for e in sides]


def _house(edit: Edit) -> dict:
    """Поля дома из правки; то, чего в запросе нет (`None` у цветов), в разметке не меняется."""
    if edit.house is None:
        return {}
    fields = {k: v for k, v in edit.house if k != "second_material"}
    return {k: v for k, v in fields.items() if k != "colors" or v is not None}


def _marks(edit: Edit, count: int) -> dict[str, list]:
    """Присланные списки отметок; отметка на стороне, которой нет, — ошибка, а не потерянная."""
    found = {f: getattr(edit, f) for f in MARK_FIELDS.values() if getattr(edit, f) is not None}
    for field, marks in found.items():
        for mark in marks:
            if mark.side >= count:
                raise ValueError(f"{field}: нет стороны {mark.side}, сторон {count}")
    return found


def check_materials(m: Markup, kinds: Collection[str]) -> None:
    """Виды отделки дома есть в `library.toml`: страница дала список, но запрос пишут и руками."""
    named = {"material": m.material, "plinth_material": m.plinth_material,
             "trim_material": m.trim_material,
             **{f"zone[{i}]": z.material for i, z in enumerate(zones(m))}}
    if bad := [f"{f}={k}" for f, k in named.items() if k is not None and k not in kinds]:
        raise ValueError(f"{m.id}: виды не из library.toml: {', '.join(bad)}")


def zones(m: Markup) -> list[ZoneMark]:
    return [z for e in m.sides for z in e.zones]


def uncolored(edit: Edit) -> Edit:
    """Правка без проверки цветов — для предпросмотра: роли дома меняются на ходу, цвета сверяются
    при сохранении."""
    if edit.house is None:
        return edit
    return edit.model_copy(update={"house": edit.house.model_copy(update={"colors": {}})})


def house_fields(m: Markup) -> dict:
    """Поля дома для панели правки: те же, что `HouseEdit`, как записаны в разметке; вид второй
    отделки — первой зоны дома (вид один, `manual.palette_roles`)."""
    fields = m.model_dump(mode="json", include=set(HouseEdit.model_fields) - {"second_material"})
    return {**fields, "second_material": next((z.material for z in zones(m)), None)}


def side_marks(m: Markup, k: int) -> dict[MarkKind, list[dict]]:
    """Отметки стороны k для страницы, по видам."""
    return {kind: [x.model_dump(mode="json") for x in getattr(m, field) if x.side == k]
            for kind, field in MARK_FIELDS.items()}


def round_units(m: Markup) -> Markup:
    return m.model_copy(update={
        "plinth": round(m.plinth, UNIT_ROUND),
        "floor_heights": [round(h, UNIT_ROUND) for h in m.floor_heights]})


def geometry(m: Markup, k: int) -> dict:
    """Линии стороны k для страницы, pt листа: земля, чистый пол, верх этажей — и масштаб вида."""
    e = m.sides[k]
    return {"ground": m.ground_y(e), "floor": e.floor, "tops": m.tops_y(e),
            "pt_per_unit": m.scale(e), "px_per_m": m.px_per_m(e)}
