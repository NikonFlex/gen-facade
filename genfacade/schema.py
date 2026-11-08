"""Типы модуля — сущности спек facade, plan-input и data (openspec/specs/).

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


class CalibrationRow(StrEnum):
    """Строка калибровки метрик — подмена ответа модели; имя папки и строки таблицы
    (metrics/calibrate.py, metrics/realtest.py)."""

    GENERATOR = "generator"
    RANDOM = "random"
    FOREIGN = "foreign"
    CONSTANT = "constant"
    EMPTY = "empty"


class Refusal(StrEnum):
    """Код отказа, который доходит до человека: в ответе смотрелки (`detail.code`), в
    meta.json прогона и в ответе модели строки realtest («refusal»). Текст — REFUSAL_TEXT;
    разные причины — разные коды (docs/clean-contour.md, п. 6, 17)."""

    PLAN_REJECTED = "plan_rejected"            # план не читается или дефектен (PlanError)
    MODEL_NO_ANSWER = "model_no_answer"        # за все попытки ни одного годного ответа
    MODEL_MISSING = "model_missing"            # нет чекпойнта
    MODEL_MISMATCH = "model_mismatch"          # модель учили на другой записи токенов
    HOUSE_OUT_OF_MODEL = "house_out_of_model"  # дом модель не прочтёт: стаб, окно, словарь
    HOUSE_NOT_BUILT = "house_not_built"        # 3D: контур не собирается в дом
    INVALID_REQUEST = "invalid_request"        # запрос не прошёл проверку схемы
    NO_PLAN = "no_plan"
    NO_RUN = "no_run"
    NO_SHEET = "no_sheet"                      # у прогона нет листа фасадов
    NO_SAMPLE = "no_sample"
    NO_REVIEW = "no_review"                    # смотрелка запущена без --review
    NO_REVIEW_ITEM = "no_review_item"          # нет дома, места или листа проверки


REFUSAL_TEXT = {
    Refusal.PLAN_REJECTED: "план отклонён",
    Refusal.MODEL_NO_ANSWER: "модель не ответила",
    Refusal.MODEL_MISSING: "модели нет",
    Refusal.MODEL_MISMATCH: "модель не подходит к записи токенов",
    Refusal.HOUSE_OUT_OF_MODEL: "дом модели не по силам",
    Refusal.HOUSE_NOT_BUILT: "дом не собрать по контуру",
    Refusal.INVALID_REQUEST: "запрос не прошёл проверку",
    Refusal.NO_PLAN: "нет плана",
    Refusal.NO_RUN: "нет прогона",
    Refusal.NO_SHEET: "у прогона нет листа фасадов",
    Refusal.NO_SAMPLE: "нет примера",
    Refusal.NO_REVIEW: "проверка не включена: genfacade serve --review <папка realtest>",
    Refusal.NO_REVIEW_ITEM: "нет в проверке",
}


class Refused(ValueError):
    """Отказ с кодом из Refusal; текст исключения — подробность к тексту кода."""

    def __init__(self, code: Refusal, detail: str):
        super().__init__(detail)
        self.code = code

    def record(self) -> dict:
        """Отказ в JSON — одинаково в ответе API, meta.json и ответе модели."""
        return refusal_record(self.code, str(self))


def refusal_record(code: Refusal, detail: str | list[str]) -> dict:
    return {"code": code, "text": REFUSAL_TEXT[code], "detail": detail}


class ElementClass(StrEnum):
    """11 классов объектов CMP + классы коттеджей (спека facade, «Элемент», класс)."""

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
    CANOPY = "canopy"


OPENINGS = (ElementClass.WINDOW, ElementClass.DOOR, ElementClass.GARAGE_DOOR)  # проёмы стены


class BuildingType(StrEnum):
    COTTAGE = "cottage"
    APARTMENT = "apartment"


class RoofKind(StrEnum):
    """Вид крыши дома (gf#320): скаты строит код развёртки (roof.py), модель ставит элементы
    стены до карниза."""

    FLAT = "flat"
    GABLE = "gable"  # двускатная: скаты от длинных сторон, фронтоны на коротких
    HIP = "hip"      # вальмовая: скаты от всех сторон
    SHED = "shed"    # односкатная: скат от одной длинной стороны вверх к другой


class OpeningKind(StrEnum):
    """Проём плана (спека plan-input, «Проём плана», вид)."""

    WINDOW = "window"
    DOOR = "door"
    ENTRANCE = "entrance"


# Виды проёма плана, которые на фасаде — дверь. Набор явный, а не «всё, что не окно»: новый вид
# проёма не должен молча попасть в двери — тест в test_schema.py падает, пока вид не разнесён.
DOOR_OPENING_KINDS = frozenset({OpeningKind.DOOR, OpeningKind.ENTRANCE})
# Класс проёма стены → вид проёма плана (вход — одна из дверей, его выбирает сторона отдельно).
PLAN_KIND = {
    ElementClass.WINDOW: OpeningKind.WINDOW,
    ElementClass.DOOR: OpeningKind.DOOR,
    ElementClass.GARAGE_DOOR: OpeningKind.DOOR,
}
# Классы проёмов стены, которые на плане — дверь: из двух таблиц выше, а не вторым списком.
DOOR_CLASSES = tuple(c for c in OPENINGS if PLAN_KIND[c] in DOOR_OPENING_KINDS)


class Source(StrEnum):
    """Откуда данные: система, выдавшая план (Plan.source), и датасет примера (Sample.source)."""

    GENPLAN = "genplan"
    MKD = "mkd"
    SYNTHETIC = "synthetic"
    BUILDINGNET = "buildingnet"
    BIO = "bio"
    MANUAL = "manual"
    CMP = "cmp"
    HZNU = "hznu"
    LOD3 = "lod3"
    LSAA = "lsaa"


class Split(StrEnum):
    TRAIN = "train"
    VAL = "val"
    TEST = "test"


class Device(StrEnum):
    """Где учить модель (config/train.toml): auto — GPU, если PyTorch его видит."""

    AUTO = "auto"
    CUDA = "cuda"
    CPU = "cpu"


class Placement(StrEnum):
    """Как синтетика ставит проёмы (config/synthetic.toml, [openings]): rules — по правилам
    генератора, random — случайно в допустимых пределах (gf#217: формат ответа учим на синтетике,
    расстановку — на реальных домах)."""

    RULES = "rules"
    RANDOM = "random"


class ContourKind(StrEnum):
    """Вид контура синтетического дома (config/synthetic.toml, [contours], `data: Ступени данных`):
    прямоугольник — ступень 1, остальные — ступень 3."""

    RECT = "rectangle"
    L = "l"          # прямоугольник с вырезанным углом
    T = "t"          # перекладина с ножкой посередине
    U = "u"          # прямоугольник с вырезом посередине стороны
    ANNEX = "annex"  # пристройка не вровень с углами
    BAY = "bay"      # эркер: мелкая пристройка без перегородки


class HouseScore(StrEnum):
    """Оценка правдоподобия одного дома (`metrics.realism.house_scores`, gf#245): density — стены
    дома в шарах эталонных стен по всем признакам сразу; marginal — по каждому признаку отдельно."""

    DENSITY = "density"
    MARGINAL = "marginal"


class TextKind(StrEnum):
    """Как получено описание дома (`data: Описания из разметки`)."""

    TEMPLATE = "template"
    PARAPHRASE = "paraphrase"
    MANUAL = "manual"


class VariantKind(StrEnum):
    """Вид проёма (спека facade, «Элемент», вариант). У двери — `DOOR_KINDS`, а дверь без варианта
    — глухая; остальные — виды окна. Форма окна, если она не прямоугольник, — тоже вид (gf#319):
    рамка остаётся прямоугольником, контур по ней считает window_shape.py."""

    REGULAR = "regular"
    PANORAMIC = "panoramic"
    CORNER = "corner"
    STRIP = "strip"
    GLAZED = "glazed"    # дверь со стеклом в полотне
    TRANSOM = "transom"  # дверь с остеклённой фрамугой над полотном, в высоте элемента
    SLOPE = "slope"      # окно во фронтоне с верхом по скату: трапеция, пятиугольник у конька
    ARCH = "arch"        # окно с полукруглым верхом
    OVAL = "oval"        # круглое или овальное окно, вписанное в рамку


DOOR_KINDS = (VariantKind.GLAZED, VariantKind.TRANSOM)


class FixedField(StrEnum):
    """Поле элемента, заданное условием, а не моделью."""

    X = "x_m"
    W = "w_m"


class ZoneRole(StrEnum):
    PLINTH = "plinth"
    MAIN = "main"
    ACCENT = "accent"
    BAND = "band"


class PaletteRole(StrEnum):
    """Роль материала в палитре дома: так же названы материалы (`Material.id`) у стаба шага 1
    и у синтетики (`generation: Стаб шага 1`)."""

    MAIN = "main"
    PLINTH = "plinth"
    ACCENT = "accent"
    TRIM = "trim"
    ROOF = "roof"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class Rule(StrEnum):
    """Правила валидатора (`evaluation: Ошибки геометрии`); что проверяет каждое — validate.py."""

    SVG_PARSE = "svg_parse"
    OUTSIDE = "outside"
    OVERLAP = "overlap"
    FORBIDDEN = "forbidden"
    PLAN_FORBIDDEN = "plan_forbidden"  # окно плана в запретной зоне — предупреждение (gf#156)
    PLAN_OPENING = "plan_opening"
    CORNER = "corner"
    FLOOR_ALIGN = "floor_align"
    AXIS_ALIGN = "axis_align"
    # геометрический брак листа (gf#242): validate.DEFECTS
    DOOR_LOW = "door_low"          # дверь ниже нормы свода
    CORNICE = "cornice"            # карниз на проёме или его выводимом элементе
    FINISH = "finish"              # часть стены без отделки, зона обрывается посреди стены
    ROOF_FLAT = "roof_flat"        # скатная крыша не строится над этим контуром (gf#320)
    SLOPE = "slope"                # окно во фронтоне ближе отступа к скату (gf#321)


class Trim(StrEnum):
    """Выводимый элемент проёма (`facade: Состав фасада по уровням`, gf#212): модель ставит у
    проёма только признак, прямоугольник считает код (derive.py) по виду дома и своду правил."""

    SILL = "sill"          # подоконник под окном
    CASING = "casing"      # наличник по бокам и сверху окна
    SHUTTERS = "shutters"  # пара ставен по бокам окна
    CANOPY = "canopy"      # козырёк над дверью


DEFAULT_DOOR = "plain"  # вид полотна двери по умолчанию — запись config/derive.toml
NONE_KIND = "none"  # вида у дома нет; остальные виды — записи config/derive.toml


class SillShape(StrEnum):
    """Рисунок подоконника на листе и форма в 3D; вид дома выбирает форму и размеры записью
    config/derive.toml (gf#318)."""

    SHELF = "shelf"  # тонкая полка
    WEDGE = "wedge"  # плита с отливом: уклон наружу


class CasingShape(StrEnum):
    """Рисунок наличника: рамка по бокам и сверху окна, сверху — сандрик."""

    FRAME = "frame"
    PEDIMENT = "pediment"  # треугольный сандрик над рамкой
    SEGMENT = "segment"    # сегментный (дуга) сандрик над рамкой


class ShutterShape(StrEnum):
    """Рисунок створки ставни; ширину створки задаёт окно, а не вид."""

    PANEL = "panel"        # две филёнки
    LOUVER = "louver"      # жалюзи: планки через шаг
    BOARD = "board"        # дощатые: вертикальные доски
    BATTEN_Z = "batten_z"  # доски на двух планках с диагональю


class CanopyShape(StrEnum):
    """Рисунок и форма козырька над дверью."""

    SLAB = "slab"        # плита с уклоном от стены
    GABLE = "gable"      # двускатный: фронтон наружу
    BRACKET = "bracket"  # плита на двух кронштейнах
    ARCHED = "arched"    # арочный: свод дугой
    POSTS = "posts"      # навес на двух столбах до пола двери


class DoorShape(StrEnum):
    """Рисунок полотна двери; остекление (стекло, фрамуга) выбирает модель, не вид дома."""

    PLAIN = "plain"            # гладкое полотно
    PANELS = "panels"          # филёнки в полотне
    DOUBLE = "double"          # двупольная: шов по центру, филёнки на каждом поле
    SIDELIGHTS = "sidelights"  # боковые стёкла по краям проёма


class GuidelineCheck(StrEnum):
    """Вид проверки правила фасада из свода (config/guidelines.toml, gf#209); что считает каждый —
    guidelines.py. none — правило по прямоугольникам фасада не проверяется."""

    NONE = "none"
    ASPECT = "aspect"
    SIZE_ROW = "size_row"
    MODULE = "module"
    SILL_HEIGHT = "sill_height"
    HEAD_HEIGHT = "head_height"
    HEAD_LINE = "head_line"
    VERTICAL_AXES = "vertical_axes"
    CORNER_DISTANCE = "corner_distance"
    PIER_MIN = "pier_min"
    OPENING_SHARE = "opening_share"
    FLOOR_OPENING_WIDTH = "floor_opening_width"
    WINDOW_TYPES = "window_types"
    DOOR_SIZE = "door_size"
    DOOR_HEIGHT = "door_height"
    DOOR_HEAD_LINE = "door_head_line"
    SILL_UNDER_WINDOW = "sill_under_window"
    CANOPY_OVER_ENTRANCE = "canopy_over_entrance"
    SHUTTER_WIDTH = "shutter_width"
    PLINTH_HEIGHT = "plinth_height"
    FLOOR_HEIGHT = "floor_height"
    LIGHT_RATIO = "light_ratio"
    HEAD_TO_EAVES = "head_to_eaves"
    LOWER_NOT_SMALLER = "lower_not_smaller"
    SYMMETRY = "symmetry"


class Region(StrEnum):
    """К каким домам применимо правило свода: ИЖС и МКД России, США, Европа, все."""

    RU_IZHS = "ru-izhs"
    RU_MKD = "ru-mkd"
    US = "us"
    EU = "eu"
    ALL = "all"


class GuidelineUse(StrEnum):
    """Куда включено правило свода; включает хозяин после замера (gf#209)."""

    METRIC = "metric"        # метрика правдоподобия, gf#210
    GUARD = "guard"          # страж при генерации и генератор синтетики, gf#213, gf#211
    VALIDATE = "validate"    # браковка валидатором шага 5, gf#242
    # synthetic, derive, train убраны (gf#293): никто их не читал — синтетика берёт guard,
    # вывод элементов (gf#212) — код шага 5; значение в конфиге без читателя молча не работало


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
    pitch_deg: float = Field(default=0.0, ge=0, lt=90)  # уклон ската; у плоской — 0
    overhang_m: float = Field(default=0.0, ge=0)        # свес за стену по горизонтали

    @model_validator(mode="after")
    def _check_pitch(self) -> "Roof":
        if (self.kind is RoofKind.FLAT) != (self.pitch_deg == 0):
            raise ValueError(f"крыша {self.kind}: уклон {self.pitch_deg}° — у плоской 0, "
                             "у скатной больше")
        return self


class HouseTrim(Model):
    """Виды выводимых элементов дома — одни на все стены (`facade: Общие параметры дома`): у проёма
    модель решает только, есть ли элемент (Trim), а вид — дома. Вид — имя записи
    config/derive.toml (открытый набор: новый вид — запись, а не правка кода и не переобучение,
    gf#318); none — элемента у дома нет. Дверь: рисунок полотна — вид дома, остекление — модель."""

    sill: str = NONE_KIND
    casing: str = NONE_KIND
    shutters: str = NONE_KIND
    canopy: str = NONE_KIND
    door: str = DEFAULT_DOOR

    def kind(self, trim: Trim) -> str:
        return getattr(self, trim)

    def has(self, trim: Trim) -> bool:
        """У дома такие элементы бывают: вид не none."""
        return self.kind(trim) != NONE_KIND


class HouseSpec(Model):
    """Параметры, общие для всех сторон дома (`facade: Общие параметры дома`)."""

    building_type: BuildingType
    floors: int = Field(ge=1)
    floor_heights_m: list[float]
    plinth_m: float = Field(ge=0)
    eaves_m: float = Field(gt=0)
    roof: Roof
    style: str = ""
    trim: HouseTrim = HouseTrim()
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
    sealed: bool = False  # заделан в глухом режиме (`plan-input: Глухой режим заделывает разрывы`)

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
    """План этажа во внутреннем формате (спека plan-input); метры, y вверх."""

    walls: list[Rect]
    outline: Polygon
    openings: list[PlanOpening] = []
    sides: list[Side] = []  # заполняет препроцессор
    scale_m_per_px: float = Field(gt=0)
    source: Source

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
    # (`generation: Режимы отличаются входом`). Один формат на оба режима.
    fixed: list[FixedField] = []

    @model_validator(mode="after")
    def _check_variant(self) -> "Element":
        if self.variant is not None:
            for_door = self.variant.kind in DOOR_KINDS
            if for_door != (self.cls is ElementClass.DOOR):
                raise ValueError(f"элемент {self.id}: вид {self.variant.kind} не для {self.cls}")
        return self


class MaterialZone(Model):
    shape: Polygon
    material: str
    role: ZoneRole

    @classmethod
    def rect(cls, role: ZoneRole, material: str, box: tuple[float, float, float, float]
             ) -> "MaterialZone":
        """Прямоугольная зона x0, y0, x1, y1 — обходом (x0 y0) (x1 y0) (x1 y1) (x0 y1), как у
        синтетики и в ответе модели (`constraints.ZONE_RECT`)."""
        x0, y0, x1, y1 = box
        return cls(role=role, material=material, shape=[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


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


class Description(Model):
    kind: TextKind
    text: str


class Sample(Model):
    """Обучающий или тестовый пример: дом с эталонными фасадами (спека data, «Пример»)."""

    # id — имя файла примера: без «/» и «..», не с «_» (так начинается опись источника).
    id: str = Field(pattern=r"^[A-Za-z0-9][\w.-]*$")
    source: Source
    split: Split
    plan: Plan | None = None  # нет у источников без плана (CMP)
    sheet: FacadeSheet
    texts: list[Description] = []

    @model_validator(mode="after")
    def _check_sides(self) -> "Sample":
        if self.plan is not None and len(self.plan.sides) != len(self.sheet.facades):
            raise ValueError(f"сторон плана {len(self.plan.sides)}, "
                             f"а фасадов {len(self.sheet.facades)}")
        return self


class Violation(Model):
    """Нарушение, найденное валидатором (спека evaluation, «Нарушение»)."""

    rule: Rule
    severity: Severity
    side: int | None = None
    element: str | None = None
    message: str
