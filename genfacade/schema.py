"""Типы модуля — поля 1:1 из specs/facade.md и specs/plan-input.md.

Модули обмениваются только этими объектами; каждый сохраняется в JSON.
Координаты — метры; на стене x вдоль стороны от её левого края (если смотреть
снаружи), y вверх от уровня земли.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

EPS = 1e-6  # допуск сравнения координат, м

Point = tuple[float, float]
Polygon = list[Point]


class Mode(StrEnum):
    WITH_OPENINGS = "with_openings"  # режим 2 «окна из плана»
    BLIND = "blind"                  # режим 1 «глухой куб»


class ElementClass(StrEnum):
    """11 классов объектов CMP + классы коттеджей (facade.md, Element.cls)."""

    WINDOW = "window"
    PILLAR = "pillar"
    SILL = "sill"
    BLIND = "blind"
    DECO = "deco"
    CORNICE = "cornice"
    BALCONY = "balcony"
    MOLDING = "molding"
    SHOP = "shop"
    FACADE = "facade"
    DOOR = "door"
    GARAGE_DOOR = "garage_door"
    PORCH = "porch"
    CHIMNEY = "chimney"


class BuildingType(StrEnum):
    COTTAGE = "cottage"
    APARTMENT = "apartment"


class RoofKind(StrEnum):
    # Пока только плоская (хозяин 01.10): скатные — на этапе модели, сюда же новыми видами.
    FLAT = "flat"


class OpeningKind(StrEnum):
    """Проём плана (plan-input.md, Opening.kind)."""

    WINDOW = "window"
    DOOR = "door"
    ENTRANCE = "entrance"


class PlanSource(StrEnum):
    GENPLAN = "genplan"
    MKD = "mkd"
    SYNTHETIC = "synthetic"
    BUILDINGNET = "buildingnet"
    BIO = "bio"
    MANUAL = "manual"


class VariantKind(StrEnum):
    REGULAR = "regular"
    PANORAMIC = "panoramic"
    CORNER = "corner"
    STRIP = "strip"


class FixedField(StrEnum):
    """Поле элемента, заданное условием, а не моделью."""

    X = "x_m"
    W = "w_m"


class ZoneRole(StrEnum):
    PLINTH = "plinth"
    MAIN = "main"
    ACCENT = "accent"
    BAND = "band"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class Rule(StrEnum):
    """Правила валидатора (evaluation.md, правило 1); что проверяет каждое — validate.py."""

    SVG_PARSE = "svg_parse"
    OUTSIDE = "outside"
    OVERLAP = "overlap"
    FORBIDDEN = "forbidden"
    PLAN_OPENING = "plan_opening"
    CORNER = "corner"
    FLOOR_ALIGN = "floor_align"
    AXIS_ALIGN = "axis_align"


class Model(BaseModel):
    # Опечатка в имени поля в JSON, написанном руками, должна падать, а не теряться молча.
    model_config = ConfigDict(extra="forbid")


class Material(Model):
    """Материал палитры дома: зоны и элементы ссылаются на него по `id`."""

    id: str
    kind: str  # вид из библиотеки материалов (config/library.toml)
    color: str | None = None  # #rrggbb; нет — цвет вида из библиотеки


class Roof(Model):
    kind: RoofKind
    material: str | None = None  # покрытие из палитры


class HouseSpec(Model):
    """Параметры, общие для всех сторон дома (facade.md, правило 2)."""

    building_type: BuildingType
    floors: int = Field(ge=1)
    floor_heights_m: list[float]
    plinth_m: float = Field(ge=0)
    eaves_m: float = Field(gt=0)
    roof: Roof
    style: str = ""
    materials: list[Material]

    @model_validator(mode="after")
    def _check(self) -> "HouseSpec":
        if len(self.floor_heights_m) != self.floors:
            n = len(self.floor_heights_m)
            raise ValueError(f"floor_heights_m: высот этажей {n}, а этажей {self.floors}")
        ids = [m.id for m in self.materials]
        if len(ids) != len(set(ids)):
            raise ValueError(f"materials: повторяются id {ids}")
        if self.roof.material is not None and self.roof.material not in ids:
            raise ValueError(f"roof.material: нет в палитре — {self.roof.material}")
        return self

    def floor_levels(self) -> list[float]:
        """Отметки низа каждого этажа и верха последнего: [цоколь, …, верх]."""
        levels = [self.plinth_m]
        for h in self.floor_heights_m:
            levels.append(levels[-1] + h)
        return levels


class Opening(Model):
    kind: OpeningKind
    x_m: float
    width_m: float = Field(gt=0)
    external: bool = True


class ForbiddenZone(Model):
    """Интервал вдоль стороны, где к наружной стене примыкает внутренняя."""

    x0_m: float
    x1_m: float


class Side(Model):
    index: int = Field(ge=0)  # по часовой стрелке от стороны входа
    length_m: float = Field(gt=0)
    orientation: Point  # наружная нормаль, единичный вектор в осях плана (y — вверх)
    openings: list[Opening] = []
    forbidden: list[ForbiddenZone] = []
    has_entrance: bool = False

    @property
    def runs_along_x(self) -> bool:
        """Стена идёт вдоль оси x плана: нормаль смотрит по y."""
        nx, ny = self.orientation
        return abs(ny) > abs(nx)


class Rect(Model):
    """Осевой прямоугольник в плане, метры, y вверх."""

    x0_m: float
    y0_m: float
    x1_m: float
    y1_m: float

    @model_validator(mode="after")
    def _check(self) -> "Rect":
        if self.x1_m - self.x0_m <= EPS or self.y1_m - self.y0_m <= EPS:
            raise ValueError(f"пустой прямоугольник: {self}")
        return self


class PlanOpening(Model):
    """Проём в координатах плана; на стороне ему соответствует `Opening`."""

    kind: OpeningKind
    rect: Rect
    external: bool = True
    sealed: bool = False  # заделан в глухом режиме (plan-input.md, правило 6)

    @model_validator(mode="after")
    def _check(self) -> "PlanOpening":
        # Глухой режим заделывает наружные разрывы, кроме входа.
        if self.sealed and (self.kind is OpeningKind.ENTRANCE or not self.external):
            raise ValueError(f"заделан может быть только наружный проём, не вход: {self.kind}")
        return self


def signed_area(poly: Polygon) -> float:
    """Площадь со знаком (формула шнурования): меньше нуля — обход по часовой стрелке."""
    pairs = zip(poly, poly[1:] + poly[:1], strict=True)
    return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in pairs) / 2


class Plan(Model):
    """План этажа во внутреннем формате (plan-input.md); метры, y вверх."""

    walls: list[Rect]
    outline: Polygon
    openings: list[PlanOpening] = []
    sides: list[Side] = []  # заполняет препроцессор
    scale_m_per_px: float = Field(gt=0)
    source: PlanSource

    @model_validator(mode="after")
    def _check_outline(self) -> "Plan":
        if len(self.outline) < 3:
            raise ValueError(f"outline: точек {len(self.outline)}, нужно не меньше трёх")
        if signed_area(self.outline) > -EPS:
            raise ValueError("outline: обход должен быть по часовой стрелке")
        return self


class OpeningVariant(Model):
    kind: VariantKind = VariantKind.REGULAR
    cols: int = Field(default=1, ge=1)  # деление рамы на створки
    rows: int = Field(default=1, ge=1)


class Element(Model):
    id: str
    cls: ElementClass
    x_m: float
    y_m: float
    w_m: float = Field(gt=0)
    h_m: float = Field(gt=0)
    floor: int | None = None
    parent: str | None = None  # id окна для подоконника, ставен
    material: str | None = None
    variant: OpeningVariant | None = None
    # Поля, заданные условием, а не моделью: в режиме 2 у проёма из плана — x и ширина
    # (generation.md, п. 4). Один формат на оба режима.
    fixed: list[FixedField] = []


class MaterialZone(Model):
    shape: Polygon
    material: str
    role: ZoneRole


class SideFacade(Model):
    side: Side
    elements: list[Element] = []
    zones: list[MaterialZone] = []
    # Не генерируется: прямоугольник стены считает развёртка (unfold.py) из HouseSpec и стороны.
    silhouette: Polygon | None = None

    @model_validator(mode="after")
    def _check_parents(self) -> "SideFacade":
        ids = [e.id for e in self.elements]
        if len(ids) != len(set(ids)):
            raise ValueError(f"сторона {self.side.index}: повторяются id элементов")
        for e in self.elements:
            if e.parent is not None and e.parent not in ids:
                raise ValueError(f"элемент {e.id}: нет родителя {e.parent}")
        return self


class FacadeSheet(Model):
    """Результат запроса: параметры дома и фасады всех сторон."""

    spec: HouseSpec
    facades: list[SideFacade]

    @model_validator(mode="after")
    def _check_materials(self) -> "FacadeSheet":
        palette = {m.id for m in self.spec.materials}
        for f in self.facades:
            used = [e.material for e in f.elements if e.material] + [z.material for z in f.zones]
            missing = sorted(set(used) - palette)
            if missing:
                raise ValueError(f"сторона {f.side.index}: материалов нет в палитре — {missing}")
        return self


class Violation(Model):
    """Нарушение, найденное валидатором (evaluation.md, Violation)."""

    rule: Rule
    severity: Severity
    side: int | None = None
    element: str | None = None
    message: str
