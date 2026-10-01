"""Типы модуля — поля 1:1 из specs/facade.md и specs/plan-input.md.

Модули обмениваются только этими объектами; каждый сохраняется в JSON.
Координаты — метры; на стене x вдоль стороны от её левого края (если смотреть
снаружи), y вверх от уровня земли.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EPS = 1e-6  # допуск сравнения координат, м

Point = tuple[float, float]
Mode = Literal["with_openings", "blind"]  # режим 2 «окна из плана» / режим 1 «глухой куб»
Polygon = list[Point]


def top_y(*polygons: Polygon) -> float:
    """Самая высокая точка нескольких многоугольников."""
    return max(y for poly in polygons for _, y in poly)

# 11 классов объектов CMP + классы коттеджей (facade.md, Element.cls)
ElementClass = Literal[
    "window", "pillar", "sill", "blind", "deco", "cornice", "balcony",
    "molding", "shop", "facade", "door", "garage_door", "porch", "chimney",
]


class Model(BaseModel):
    # Опечатка в имени поля в JSON, написанном руками, должна падать, а не теряться молча.
    model_config = ConfigDict(extra="forbid")


class Material(Model):
    """Материал палитры дома: зоны и элементы ссылаются на него по `id`."""

    id: str
    kind: str  # вид из библиотеки материалов (config/library.toml)
    color: str | None = None  # #rrggbb; нет — цвет вида из библиотеки


class Roof(Model):
    kind: Literal["flat", "gable", "hip", "shed"]
    pitch_deg: float = Field(ge=0, lt=90)
    ridge_axis: Literal["x", "y"] = "x"  # конёк вдоль оси плана
    overhang_m: float = Field(ge=0)
    material: str | None = None  # покрытие из палитры


class HouseSpec(Model):
    """Параметры, общие для всех сторон дома (facade.md, правило 2)."""

    building_type: Literal["cottage", "apartment"]
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
    kind: Literal["window", "door", "entrance"]
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

    kind: Literal["window", "door", "entrance"]
    rect: Rect
    external: bool = True
    sealed: bool = False  # заделан в глухом режиме (plan-input.md, правило 6)

    @model_validator(mode="after")
    def _check(self) -> "PlanOpening":
        # Глухой режим заделывает наружные разрывы, кроме входа.
        if self.sealed and (self.kind == "entrance" or not self.external):
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
    source: Literal["genplan", "mkd", "synthetic", "buildingnet", "bio", "manual"]

    @model_validator(mode="after")
    def _check_outline(self) -> "Plan":
        if len(self.outline) < 3:
            raise ValueError(f"outline: точек {len(self.outline)}, нужно не меньше трёх")
        if signed_area(self.outline) > -EPS:
            raise ValueError("outline: обход должен быть по часовой стрелке")
        return self


class OpeningVariant(Model):
    kind: Literal["regular", "panoramic", "corner", "strip"] = "regular"
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
    fixed: list[Literal["x_m", "w_m"]] = []


class MaterialZone(Model):
    shape: Polygon
    material: str
    role: Literal["plinth", "main", "accent", "band"]


class SideFacade(Model):
    side: Side
    elements: list[Element] = []
    zones: list[MaterialZone] = []
    # Не генерируются: считает развёртка (unfold.py) из HouseSpec и сторон.
    silhouette: Polygon | None = None  # шаг 3 — прямоугольник стены; шаг 6 — с фронтоном
    roof: Polygon | None = None  # видимая часть крыши на этой стороне — с шага 6

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

    rule: str
    severity: Literal["error", "warning"]
    side: int | None = None
    element: str | None = None
    message: str
