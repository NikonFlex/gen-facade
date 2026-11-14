"""Настройки, вынесенные из кода: материалы, лист, смотрелка, план, проверка, данные,
синтетика, токены, обучение, модели.

По умолчанию — файлы этой папки. Свой конфиг — папка с любыми из тех же файлов:
TOML сливается с умолчаниями поключно, sheet.css дописывается после умолчаний
(правила CSS переопределяют предыдущие). Опечатка в ключе — ошибка, а не молчание.
Здесь только настройки приложения; данные заглушек моделей — в genfacade/models/.
"""

import tomllib
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from genfacade.datasets.buildingnet.mesh import Label
from genfacade.schema import (
    NONE_KIND,
    CanopyShape,
    CasingShape,
    CheckState,
    ContourKind,
    DataAttr,
    DataRole,
    Device,
    DoorShape,
    DormerRoof,
    ElementClass,
    Facing,
    GuidelineCheck,
    GuidelineUse,
    HouseScore,
    HouseTrim,
    LevelKind,
    LlmProvider,
    MarkKind,
    MarkShape,
    Mode,
    PaletteRole,
    Placement,
    PlanShape,
    Region,
    RejectReason,
    Roof,
    RoofKind,
    RuleDraw,
    RuleFrom,
    RuleVariant,
    RunOutcome,
    ShutterShape,
    SillShape,
    Source,
    Split,
    Trim,
    VariantKind,
    ZoneRole,
)

DEFAULTS = files(__package__)
DOOR_FIELD = "door"  # поле HouseTrim с видом полотна двери: у остальных полей none допустим


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Fill(Section):
    wall: str
    glass: str
    other: str


class Course(Section):
    """Ряд рисунка материала: высота и места вертикальных швов внутри периода рисунка."""

    h_m: float
    joints_m: list[float]


class Hatch(Section):
    """Рисунок вида материала на листе (SVG `<pattern>` в метрах фасада): ряды снизу вверх,
    повторяются по высоте и по ширине `width_m`. vertical — рисунок повёрнут: ряды стоят
    вертикально (доска с планкой, фальц), швы идут поперёк них."""

    vertical: bool
    line_m: float     # толщина линии шва
    groove_m: float   # вторая линия рядом с каждым швом — нахлёст обшивки, планка; 0 — нет
    width_m: float    # период по ряду; без швов в ряду — любой
    courses: list[Course]


class Library(Section):
    kinds: dict[str, str]
    # Вид → вид, под которым его видит модель шага 4 (gf#317): словарь модели — виды, которыми она
    # обучена; новый вид добавляется записью здесь и переобучения не требует
    model_kinds: dict[str, str] = {}
    patterns: dict[str, Hatch]  # вид → рисунок; вида нет — зона и элемент сплошным цветом
    pattern_darken: float       # линии рисунка: каждый канал цвета материала × (1 − это)
    unhatched_cls: list[ElementClass]  # элементы этих классов рисуют себя сами
    fill: Fill
    class_fill: dict[ElementClass, str]  # опечатка в классе элемента — ошибка загрузки

    @model_validator(mode="after")
    def _kinds_are_consistent(self) -> Self:
        unknown = self.patterns.keys() - self.kinds.keys()
        if unknown:
            raise ValueError(f"рисунок у вида, которого нет в [kinds]: {sorted(unknown)}")
        bad = {k: v for k, v in self.model_kinds.items()
               if k not in self.kinds or v not in self.kinds or v in self.model_kinds}
        if bad:
            raise ValueError(f"model_kinds: вид и его образ должны быть в [kinds], а образ — "
                             f"не сам заменяемый: {sorted(bad.items())}")
        return self

    def model_kind(self, kind: str) -> str:
        """Вид материала в условии модели шага 4."""
        return self.model_kinds.get(kind, kind)


class SheetLayout(Section):
    scale: int
    columns: int
    margin_left_m: float
    margin_top_m: float
    gap_x_m: float
    gap_y_m: float


class Ground(Section):
    extend_m: float


class Levels(Section):
    offset_m: float
    shelf_left_m: float
    shelf_right_m: float
    marker_half_width_m: float
    marker_height_m: float
    text_dx_m: float
    text_above_m: float
    text_below_m: float
    merge_below_m: float


class Axes(Section):
    line_from_m: float
    line_to_m: float
    bubble_y_m: float
    bubble_radius_m: float
    text_dy_m: float
    letters: str


class Title(Section):
    y_m: float


class Preview(Section):
    width_px: int


class PlanLook(Section):
    margin_m: float
    label_offset_m: float
    forbidden_inset_m: float
    legend_margin_m: float
    legend_line_m: float
    legend_swatch_m: float
    legend_gap_m: float
    legend: dict[str, str]  # ключ — класс .plan-<ключ> в sheet.css, значение — подпись


class SpecLook(Section):
    margin_m: float
    wall_m: float
    gap_m: float
    line_m: float
    swatch_m: float
    text_dx_m: float
    text_w_m: float


class DoorLook(Section):
    glass_inset: float
    glazed_span: tuple[float, float]
    transom_share: float


class TrimLook(Section):
    louver_step_m: float
    board_step_m: float
    panel_inset: float
    slab_m: float
    bracket_at: float
    bracket_w_m: float
    post_w_m: float
    batten_at: float


class RoofDrawing(Section):
    thickness_m: float = Field(gt=0)  # кровля: одна толщина на листе, в 3D и в IFC (gf#447)


class RoofItemsLook(Section):
    """Труба и водосток на кровле (gf#454): размеры из СНиП 41-01-2003 п. 6.6.12 (труба выше
    конька на 0,5 м) и каталогов Grand Line (желоб 125 мм, труба 90 мм); цвета листа и 3D."""

    chimney_m: float = Field(gt=0)       # сторона квадратного сечения трубы в плане
    chimney_over_m: float = Field(gt=0)  # верх трубы выше конька (у односкатной — высокой кромки)
    chimney_near_m: float = Field(gt=0)  # до этого расстояния от конька верх — выше конька на over
    chimney_far_m: float = Field(gt=0)   # до этого — вровень с коньком, дальше — линия под углом
    chimney_slope_deg: float = Field(gt=0, lt=90)  # линия вниз от конька, градусов к горизонту
    gutter_m: float = Field(gt=0)        # желоб: сторона сечения
    pipe_m: float = Field(gt=0)          # водосточная труба: диаметр
    pipe_inset_m: float = Field(ge=0)    # труба от угла дома вдоль стены
    chimney_fill: str
    gutter_fill: str
class SkylightLook(Section):
    """Мансардное окно в плоскости ската (gf#456): размер, где ставится и как рисуется."""

    width_m: float = Field(gt=0)        # поперёк ската — вдоль карниза
    length_m: float = Field(gt=0)       # по скату
    min_pitch_deg: float = Field(gt=0)  # положе — окон нет
    sill_m: float = Field(ge=0)         # низ окна над карнизом по вертикали
    gap_m: float = Field(ge=0)          # между окнами ряда
    end_margin_m: float = Field(ge=0)   # от торца кровли
    ridge_margin_m: float = Field(ge=0)  # от конька по скату
    frame_m: float = Field(gt=0)        # ширина рамы: стекло — внутри неё
    lift_m: float = Field(ge=0)         # стекло выше верха кровли, чтобы не сливалось с ней


class Sheet(Section):
    sheet: SheetLayout
    ground: Ground
    levels: Levels
    axes: Axes
    door: DoorLook
    trim: TrimLook
    roof: RoofDrawing
    roof_items: RoofItemsLook
    skylight: SkylightLook
    title: Title
    preview: Preview
    plan: PlanLook
    spec: SpecLook


class Gaps(Section):
    min_opening_px: float
    min_band_overlap: float


class Outline(Section):
    jog_px: float
    stray_area: float


class Parts(Section):
    """Какие крылья дома ниже главного (gf#322, `facade: Части дома`)."""

    ratio: float       # крыло меньше этой доли площади главного — кандидат в нижнее
    wing_min_m: float  # уже этого (меньшая сторона) — выступ, а не крыло: на высоте главной части
    drop_floors: int   # на сколько этажей нижнее крыло ниже главной части, если текст молчит
    annex_shed: bool   # при генерации у пристройки односкатная крыша (gf#431); нет — крыша дома
    annex_pitch_deg: float  # её уклон
    entrance_gable_share: float    # щипец над входом по слову текста: доля участка стены (gf#455)
    entrance_gable_pitch_deg: float  # его уклон
    entrance_gable_min_m: float    # уже этого щипец не строится


class PlanConfig(Section):
    gaps: Gaps
    outline: Outline
    parts: Parts


GuidelineParams = dict[str, ElementClass | float | list[float]]


class Checks(Section):
    """Шаг 5: допуски привязки и валидатора (config/checks.toml); norms — параметры правил свода
    с `use = ["validate"]` по виду проверки (gf#242): их не пишут в checks.toml, их кладёт `load`
    из guidelines.toml — число нормы в одном месте."""

    eps_m: float
    align_m: float
    snap_m: float
    window_jump_m: float
    porch_min_m: float
    porch_pad_m: float
    door_spread_m: float
    door_min_w_m: float
    corner_min_m: float
    slope_offset_m: float  # окно во фронтоне — не ближе к скату (gf#321)
    attic_knee_m: float    # окно под скатом — низом не ниже карниза на столько (gf#321)
    slope_share: float = Field(gt=0, le=1)  # доля рамки окна `slope` в стене (gf#319)
    pane_min_w_m: float = Field(gt=0)  # ячейка стекла окна не уже (gf#413)
    pane_min_h_m: float = Field(gt=0)  # ... и не ниже
    norms: dict[GuidelineCheck, GuidelineParams] = {}


class Server(Section):
    host: str
    port: int


class ViewerPaths(Section):
    runs_dir: Path
    plans_dirs: list[Path]


class ModeLabel(Section):
    title: str
    hint: str


class Tone(StrEnum):
    """Окраска состояния на странице: класс темы смотрелки (viewer/static/theme.css, .status)."""

    OK = "ok"
    BAD = "bad"
    WARN = "warn"
    MUTED = "muted"


class OutcomeLabel(Section):
    """Итог прогона на странице «Дома» (gf#356): подпись и окраска."""

    title: str
    tone: Tone


class Labels(Section):
    """Подписи смотрелки к значениям enum из schema.py: страница берёт их отсюда."""

    mode: dict[Mode, ModeLabel]
    cls: dict[ElementClass, str]
    role: dict[ZoneRole, str]
    variant: dict[VariantKind, str]
    roof: dict[RoofKind, str]
    outcome: dict[RunOutcome, OutcomeLabel]
    style: dict[str, str]           # стиль стаба шага 1 (models.toml, style_words) — «Новый дом»
    trim: dict[Trim, str]           # выводимый элемент — «Новый дом»
    shape: dict[ContourKind, str]   # вид контура случайного плана — «Новый дом»
    kind: dict[str, str]            # вид материала стен, который можно назвать в тексте
    color: dict[str, str]           # цвет, который можно назвать в тексте: слово → русское


class SamplesView(Section):
    shown: int


class RuleItem(Section):
    """Правило на странице «Правила» (gf#356): число берётся из конфига, а не пишется сюда."""

    id: str
    title: str
    text: str                       # что утверждает правило и кто его держит
    number_from: RuleFrom
    key: str                        # поле Checks или параметр правила свода
    guideline: str | None = None    # правило свода: его параметр, источники и цитаты
    unit: str = "м"
    holds: str                      # где держится: привязка (шаг 5), валидатор, страж синтетики
    draw: RuleDraw
    good: float                     # на картинке «так» значение = число × good
    bad: float                      # на картинке «не так» значение = число × bad


class RuleSheet(Section):
    """Стена, на которой рисуются картинки правил: размеры — одни на все правила."""

    wall_m: float
    depth_m: float
    window_m: tuple[float, float]
    door_m: tuple[float, float]
    sill_m: float


class Rules(Section):
    sheet: RuleSheet
    captions: dict[RuleVariant, str]   # подпись под картинкой «так» и «не так»
    item: list[RuleItem]


class DataSetLabel(Section):
    """Набор данных на странице «Данные»: чем он служит и в каком порядке."""

    title: str
    role: DataRole
    note: str       # что это
    origin: str     # откуда и на каких условиях
    how: str        # как участвует в обучении и что генерирует
    modes: str      # какие режимы шага 4 из него получаются


class DataView(Section):
    """Страница «Данные» (gf#356): сколько домов корпуса читать для долей, сколько примеров
    показывать, подписи наборов и признаков."""

    stats_sample: int = Field(gt=0)
    examples: int = Field(gt=0)
    page_size: int = Field(gt=0)
    sheet_cache: int = Field(gt=0)
    roles: dict[DataRole, str]
    shapes: dict[PlanShape, str]
    sets: dict[Source, DataSetLabel]
    attrs: dict[DataAttr, str]


class House3d(Section):
    """Дом объёмом в смотрелке: откуда three.js, разрешение текстур фасадов, цвета сцены."""

    three_url: str
    web_ifc_url: str       # просмотр IFC (gf#392): разбор файла в браузере
    web_ifc_wasm_dir: str
    selected: str
    px_per_m: int
    # потолки текстур стен (gf#353): сторона — не больше этого и не больше MAX_TEXTURE_SIZE
    # видеокарты; все стены вместе — не больше texture_budget_mpx млн пикселей (4 байта каждый)
    texture_max_px: int = Field(gt=0)
    texture_budget_mpx: float = Field(gt=0)
    roof: str
    ground: str
    background: str
    edges: str
    outline: bool  # рёбра стен, кровли и выступов линией цвета edges; выкл — углы читает свет
    # выступы стены (gf#268): глубина в метрах для зон этих ролей и элементов этих классов
    relief_role: dict[ZoneRole, float]
    relief_cls: dict[ElementClass, float]
    # формы выступов (gf#305): ступень крыльца, плита с уклоном, отлив цоколя, профиль карниза
    riser_m: float = Field(gt=0)
    tread_m: float = Field(gt=0)
    slope_edge: float = Field(gt=0, lt=1)
    plinth_wash_m: float = Field(ge=0)
    cornice_steps: list[tuple[float, float]] = Field(min_length=1)
    window_out_m: float = Field(ge=0)  # окно во фронтоне — на столько наружу от стены (gf#321)


class IfcNames(Section):
    """Имена объектов IFC; в `{…}` подставляется номер, сторона или id элемента листа."""

    project: str
    site: str
    building: str
    storey: str
    wall: str
    joint_wall: str
    window: str
    door: str
    garage_door: str
    opening: str
    slab: str
    roof: str
    roof_slab: str
    skylight: str
    shutter: str
    canopy: str
    porch: str
    chimney: str
    gutter: str   # {n} — номер
    pipe: str     # {n} — номер


class IfcPset(Section):
    facade: str


class IfcExport(Section):
    """Выгрузка дома в BIM (config/ifc.toml, gf#392): размеры объектов, имена, допуск."""

    wall_thickness_m: float = Field(gt=0)
    slab_m: float = Field(gt=0)
    roof_seat_m: float = Field(gt=0)
    joint_wall_m: float = Field(gt=0)
    shutter_m: float = Field(gt=0)
    window_depth_m: float = Field(gt=0)
    opening_margin_m: float = Field(ge=0)
    glass_transparency: float = Field(ge=0, le=1)
    tolerance: float = Field(gt=0)
    names: IfcNames
    pset: IfcPset


class Ifc(Section):
    ifc: IfcExport


class DormerNames(Section):
    """Имена объектов дормера в IFC; {n} — номер дормера с единицы."""

    face: str
    cheek: str


class DormerRules(Section):
    """Слуховые окна (config/dormer.toml, gf#457): размеры лица, крыши и окна — для кода, который
    их строит (genfacade/dormers.py); слова и вид по умолчанию для стаба — в SpecStub.dormer."""

    face_offset_m: float = Field(gt=0)
    face_top_m: float = Field(gt=0)
    min_pitch_deg: float = Field(gt=0, lt=90)
    below_ridge_m: float = Field(ge=0)
    gable_pitch_deg: float = Field(gt=0, lt=90)
    shed_pitch_deg: float = Field(gt=0, lt=90)
    window_side_m: float = Field(ge=0)
    window_sill_m: float = Field(ge=0)
    window_head_m: float = Field(ge=0)
    window_min_h_m: float = Field(gt=0)
    names: DormerNames


class Review(Section):
    """Слепая проверка листов глазами (gf#268, viewer/review.py): какие строки реального теста
    показывать на доме, от чего перемешивать их места, по каким режимам идти и показывать ли
    настоящий дом отдельно."""

    rows: list[str]
    seed: int
    modes: list[Mode]
    reference: bool


Size = tuple[float, float]


class MarkupColors(Section):
    """Цвета рамок на странице правки (gf#348); те же берёт `tools/markup.py overlay` — картинка
    сверки и страница не расходятся. Имена CSS: их понимают и браузер, и Pillow."""

    cls: dict[ElementClass, str]   # рамка элемента по классу
    levels: str                    # земля, чистый пол, этажи, края стены
    zone: str                      # вторая отделка
    outline: str                   # силуэт стены выше карниза
    roof: str
    selected: str                  # выбранная рамка


class MarkupLabels(Section):
    state: dict[CheckState, str]
    reason: dict[RejectReason, str]
    level: dict[LevelKind, str]
    house: dict[str, str]          # поле дома на панели правки (gf#470): поле или trim.<элемент>
    mark_kind: str                 # подпись списка видов у выбранной отметки
    build_sheet: str               # заголовок листа, собранного модулем из разметки (gf#470)
    build_house: str               # заголовок 3D дома из разметки
    build_plan: str                # заголовок плана, собранного сборщиком разметки
    build_source_plan: str         # подпись исходного плана листа рядом с ним
    build_wait: str                # пока дом собирается
    mark_depth: str                # подпись поля выноса отметки от стены вида (gf#471)
    variant_kind: str              # подписи полей вида проёма у выбранного окна, двери (gf#471)
    variant_cols: str
    variant_rows: str
    no_variant: str                # «вида нет» — вариант проёма не записан
    empty_kind: str                # «вид не записан» в списках видов
    delete_mark: str
    delete_zone: str
    no_color: str                  # у роли палитры цвет не задан (gf#470)
    role: dict[PaletteRole, str]   # подпись цвета роли палитры


class MarkStyle(Section):
    """Отметка на виде (gf#470): подпись кнопки, как ставится, цвет и поля новой отметки."""

    label: str
    shape: MarkShape
    color: str
    size_m: Size | None = None     # от касания: ширина × высота, м; у касания-точки нет
    defaults: dict[str, str | int | float] = {}   # поля новой отметки, кроме места на виде
    depth: bool = False            # есть вынос от стены вида, м (gf#471)


class ZoneStyle(Section):
    """Зона второй отделки на виде (gf#470): подпись кнопки и размер от касания, м."""

    label: str
    size_m: Size


class MarkupEditor(Section):
    """Страница правки разметки (/markup, gf#348, viewer/markup.py): откуда очередь домов, куда
    пишется правка, как жмутся листы и какого размера рамка от касания."""

    folder: Path                   # <дом>.toml очереди; правка пишется туда же (папка разметки)
    source: str                    # ключ `data.manual.paths.pdf_dirs`: где листы домов
    state_file: str                # состояние очереди — в папке разметки
    original_dir: str              # исходная разметка автоматики: подпапка, сборщик её не читает
    cache_dir: Path                # сжатые листы
    image_max_side: int            # длинная сторона листа для страницы, px
    add_classes: list[ElementClass]  # что можно добавить кнопкой; размер — в default_size_m
    default_size_m: dict[ElementClass, Size]  # рамка от касания: ширина и высота, м
    min_box_m: float               # рамка меньше этого при отпускании — касание, не рамка
    mark_depth_step_m: float       # шаг поля выноса отметки от стены вида (труба, крыльцо; gf#471)
    view_pad_m: float              # поле вокруг рисунка фасада в окне вида стороны, м вида (gf#470)
    ink_level: int                 # серость пикселя листа (0–255), темнее — рисунок, а не бумага
    build_delay_ms: int            # пауза после правки перед пересборкой листа и 3D, мс
    plan_image: str                # исходная страница плана в папке листа дома (gf#470)
    build_height_px: int           # высота панели «лист модуля и 3D» на странице, px (gf#470)
    house_step: dict[str, float]   # шаг числовых полей дома на панели правки (gf#470)
    marks: dict[MarkKind, MarkStyle]
    zone: ZoneStyle
    colors: MarkupColors
    labels: MarkupLabels

    @model_validator(mode="after")
    def _complete(self) -> Self:
        """Подпись и цвет есть у каждого значения enum, размер — у каждого добавляемого класса."""
        need = {
            "цвет класса": (set(self.colors.cls), set(ElementClass)),
            "подпись состояния": (set(self.labels.state), set(CheckState)),
            "подпись причины": (set(self.labels.reason), set(RejectReason)),
            "подпись линии": (set(self.labels.level), set(LevelKind)),
            "подпись роли": (set(self.labels.role), set(PaletteRole)),
            "размер рамки": (set(self.default_size_m), set(self.add_classes)),
            "отметка": (set(self.marks), set(MarkKind)),
        }
        for what, (have, want) in need.items():
            if have != want:
                raise ValueError(f"{what}: не хватает или лишнее {sorted(have ^ want)}")
        return self


class CatalogSample(Section):
    """Образец, на котором каталог рисует вид (gf#354): дом и стена того же размера для каждого
    вида, чтобы картинки сравнивались. Дом — параметры стаба шага 1 (models/stub_data), здесь
    только размеры; окно и дверь — по виду, остальное — как у листа."""

    width_m: float                # дом: длинная сторона
    depth_m: float                # дом: короткая сторона, на ней фронтон и вход
    wall_m: float                 # отдельная стена для окон, дверей и выводимых элементов
    sill_m: float                 # низ окна над землёй
    window_at: float              # окно и дверь рядом на одной стене (отделки): где стоит окно,
    door_at: float                # где дверь — доля свободной длины стены, 0 — слева, 1 — справа
    door_m: Size
    window_m: dict[str, Size]     # вид окна → ширина × высота; `default` — вида нет в таблице


class CatalogSection(Section):
    """Раздел каталога: заголовок и пояснение для страницы, а откуда брать источник вида в
    docs/library-catalog.md — подзаголовки (по куску текста) и строка таблицы (по куску первой
    ячейки, если в таблице вперемешку подоконники и наличники)."""

    title: str
    note: str = ""
    doc_headings: list[str] = []
    doc_row: str = ""


class Catalog(Section):
    """Вкладка «Каталог» смотрелки (/catalog, gf#354): состав — из конфига, порядок и тексты
    разделов — отсюда. Идентификатор раздела — имя построителя в viewer/catalog.py."""

    doc: Path                     # источник видов; нет файла — источников нет
    sample: CatalogSample
    labels: dict[str, str]        # подписи к строкам «Что у вида» и группам
    sections: dict[str, CatalogSection]


class Viewer(Section):
    server: Server
    paths: ViewerPaths
    samples: SamplesView
    house3d: House3d
    review: Review
    markup: MarkupEditor
    catalog: Catalog
    data_view: DataView
    rules: Rules
    labels: Labels


class DataPaths(Section):
    samples_dir: Path


class BuildingNetPaths(Section):
    models_dir: Path
    component_labels: Path
    splits: dict[Split, Path]  # часть официального разбиения → список моделей


class BuildingNet(Section):
    """Извлечение коттеджей BuildingNet (config/data.toml, `data: Извлечение BuildingNet`)."""

    paths: BuildingNetPaths
    categories: list[str]
    door_height_m: float
    door_quantile: float
    facing_m: float
    profile_step_m: float
    min_wall_m: float
    min_coverage: float
    min_side_m: float
    min_jog_m: float
    max_sides: int
    floor_height_m: float
    max_plinth_m: float
    min_element_m: float
    inside_share: float
    wall_m: float
    material: str
    classes: dict[Label, ElementClass]  # опечатка в метке или классе — ошибка загрузки


class ManualPaths(Section):
    markup_dir: Path               # <источник>/<дом>.toml
    pdf_dirs: dict[str, Path]      # источник (папка разметки) → где его листы PDF


class MarkupCompare(Section):
    """Допуски сверки разметки с эталоном (`tools/markup_compare.py`, gf#470)."""

    tol_pitch_deg: float
    tol_overhang_m: float  # и карнизный, и фронтонный свес
    tol_plinth_m: float
    tol_floor_m: float     # высота каждого этажа
    iou_min: float         # рамка окна или двери найдена, если пересечение с эталонной не меньше


class MarkupColors(Section):
    """Снятие цветов отделки с листа (`tools/markup_colors.py`, gf#470)."""

    min_pixels: int   # у роли пикселей меньше — цвет не пишется: мест роли нет или они узкие
    line_dark: int    # пиксели темнее (средняя яркость 0–255) — линии чертежа, в медиану не идут
    paper_min: int    # медиана, у которой все каналы не ниже, — бумага чертежа, а не цвет отделки


class Manual(Section):
    """Ручная разметка реальных коттеджей (config/data.toml, `data: Реальные коттеджи — тест`)."""

    paths: ManualPaths
    length_tol_m: float
    chimney_beyond_m: float
    chimney_across_digits: int  # отступ трубы от конька округляется до стольких знаков, м (gf#471)
    eaves_tol_m: float
    wall_m: float
    inside_share: float
    link_tol_m: float
    gable_tol_m: float  # окно во фронтоне за стеной с фронтоном модуля не дальше этого (gf#321)
    trim: HouseTrim
    compare: MarkupCompare
    colors: MarkupColors


class Data(Section):
    """Данные для обучения и теста (config/data.toml, спека data)."""

    paths: DataPaths
    buildingnet: BuildingNet
    manual: Manual


Range = tuple[float, float]


class Canvas(Section):
    px_per_m: int
    margin_m: float


class HouseSize(Section):
    grid_m: float
    wall_m: float


class OpeningRules(Section):
    placement: Placement
    grid_m: float
    corner_clear_m: float
    # окно — не ближе к углу стены: правило свода window_corner_distance, когда оно в страже
    # (gf#213); в файле настроек его нет — ставит datasets/synthetic/build.rules (gf#212)
    window_corner_m: float = 0.0
    between_m: float
    widths_per_house: int
    per_bay_weights: list[float]
    entrance_long_p: float
    blind_long_p: float
    blind_short_p: float
    upper_on_axes_p: float


class Partitions(Section):
    room_m: float
    min_room_m: float
    passage_m: float


class Contours(Section):
    """Непрямоугольные контуры (config/synthetic.toml, [contours], `data: Ступени данных`)."""

    weights: dict[ContourKind, float]  # вид контура → вес; доля непрямоугольных — всё, кроме rect
    wing_min_m: float                  # крыло (прямоугольная часть дома) не уже
    arm_min_m: float                   # уступ у пристройки, ножки и эркера — от угла не меньше
    stem_depth_m: Range                # ножка T
    annex_width_m: Range
    annex_depth_m: Range
    bay_width_m: Range
    bay_depth_m: Range                 # эркер глубже 0,6 м — часть контура (gf#199)


class Composite(Section):
    """Составные крыши синтетики (config/synthetic.toml, [spec.composite], gf#431)."""

    part_p: float                  # доля скатных домов с крыльями, у которых у пристроек своя крыша
    part_pitch_deg: list[float]    # уклон односкатной крыши пристройки
    wall_gable_p: float            # доля двускатных домов со щипцом над входом
    wall_gable_share: Range        # ширина щипца — доля длины участка стены
    wall_gable_min_m: float        # щипец уже не строится
    wall_gable_pitch_deg: list[float]


class SpecRules(Section):
    floors_weights: list[float]
    grid_m: float
    styles: list[str]
    palette: dict[PaletteRole, list[str]]  # виды — из library.toml
    roof_weights: dict[RoofKind, float]    # вид крыши дома → вес (gf#320)
    composite: Composite


class Windows(Section):
    head_m: Range
    lintel_m: float
    heights_m: list[float]
    sill_m: Range
    narrow_max_w_m: float
    narrow_heights_m: list[float]
    wide_min_w_m: float
    wide_floor_p: float
    sash_max_w_m: float
    transom_min_h_m: float


class Door(Section):
    height_m: float
    transom_m: float
    weights: dict[str, float]
    glazed_panes: tuple[int, int]


class Cornice(Section):
    height_m: float
    min_m: float


class TrimWeights(Section):
    """Веса видов выводимых элементов дома (config/synthetic.toml, [facade.trim])."""

    sill: dict[str, float]
    casing: dict[str, float]
    shutters: dict[str, float]
    canopy: dict[str, float]
    door: dict[str, float]


class Finish(Section):
    weights: dict[str, float]  # ключи — схемы отделки (datasets/synthetic/zones.py, Scheme)
    entrance_pad_m: float
    wainscot_m: Range
    corner_m: float
    pier_max_m: float


class Entry(Section):
    porch_p: float


class GableWindows(Section):
    """Окна во фронтоне синтетики (config/synthetic.toml, [facade.gable], gf#321)."""

    share: float               # доля домов с двускатной крышей, у которых они есть; 0 — ни у кого
    count_weights: list[float]  # веса 0, 1, 2, 3 окон на щипцовой стене
    sill_m: tuple[float, float]  # низ окна над карнизом, от и до
    shapes: dict[VariantKind, float] = {}  # вид окна во фронтоне по форме → вес (gf#319)


class FacadeRules(Section):
    windows: Windows
    door: Door
    trim: TrimWeights
    cornice: Cornice
    finish: Finish
    entry: Entry
    gable: GableWindows


class Build(Section):
    val_share: float


class Sizes(Section):
    """Профиль размеров дома (config/synthetic.toml, [sizes.*]): значения — на сетке шага."""

    width_m: Range
    depth_m: Range
    floor_height_m: Range
    floor_height_step_m: float
    plinth_m: Range
    window_width_m: Range
    window_step_m: float
    window_widths_m: list[float] | None = None  # ряд ширин окна; нет — сетка от и до с шагом
    # отступ проёма от угла и простенок; нет — как в [openings]
    corner_clear_m: float | None = None
    between_m: float | None = None


class SizeMix(Section):
    real_share: float
    genplan: Sizes
    real: Sizes


class Synthetic(Section):
    """Генератор синтетических домов
    (config/synthetic.toml, `data: Синтетика своим генератором`)."""

    build: Build
    canvas: Canvas
    house: HouseSize
    sizes: SizeMix
    openings: OpeningRules
    partitions: Partitions
    contours: Contours
    spec: SpecRules
    facade: FacadeRules


class Tokens(Section):
    """Запись дома токенами (config/tokens.toml)."""

    grid_m: float
    max_m: float


class SillLook(Section):
    shape: SillShape
    overhang_m: float
    height_m: float


class CasingLook(Section):
    shape: CasingShape
    width_m: float
    rise_m: float = 0.0  # сандрик над рамкой


class ShutterLook(Section):
    shape: ShutterShape
    share: float


class CanopyLook(Section):
    shape: CanopyShape
    pad_m: float
    gap_m: float
    height_m: float


class DoorLeaf(Section):
    """Рисунок полотна двери: доли полотна; cols, rows — филёнок, inset — отступ (доля ширины),
    side_share — боковое стекло (доля ширины проёма)."""

    shape: DoorShape
    cols: int = 1
    rows: int = 1
    inset: float = 0.0
    side_share: float = 0.0


class RoofShape(Section):
    """Крыша дома (gf#320): уклон и свесы по виду скатной крыши — для стаба шага 1 и синтетики.
    Свес карнизный — за стену со скатом, фронтонный — за стену без ската (gf#451); у вальмовой
    фронтонного нет."""

    pitch_deg: dict[RoofKind, float]
    overhang_m: dict[RoofKind, float]
    gable_overhang_m: dict[RoofKind, float]

    def roof(self, kind: RoofKind, material: str | None) -> Roof:
        """Крыша вида kind: у плоской уклона и свеса нет, у вальмовой нет фронтонного свеса."""
        if kind is RoofKind.FLAT:
            return Roof(kind=kind, material=material)
        return Roof(kind=kind, material=material, pitch_deg=self.pitch_deg[kind],
                    overhang_m=self.overhang_m[kind],
                    gable_overhang_m=self.gable_overhang_m.get(kind))


class Derive(Section):
    """Выводимые элементы проёма (config/derive.toml, gf#212): виды дома и размеры каждого. Виды —
    открытый набор записей: новый вид добавляется записью, без переобучения модели (gf#318)."""

    canopy_min_h_m: float
    sill: dict[str, SillLook]
    casing: dict[str, CasingLook]
    shutters: dict[str, ShutterLook]
    canopy: dict[str, CanopyLook]
    door: dict[str, DoorLeaf]

    def kinds(self, name: str) -> list[str]:
        """Виды элемента дома, без none: sill, casing, shutters, canopy, door."""
        return list(getattr(self, name))

    def look(self, name: str, kind: str):
        """Запись вида; вида нет в config/derive.toml — отказ с понятным текстом, а не KeyError."""
        found = getattr(self, name)
        if kind not in found:
            raise ValueError(f"{name}: вида «{kind}» нет в derive.toml, есть {sorted(found)}")
        return found[kind]

    def find(self, name: str, kind: str):
        """Запись вида или None, если элемента у дома нет (none): у реальных домов листы бывают
        с элементом, чьего вида дом не назвал."""
        return None if kind == NONE_KIND else self.look(name, kind)

    def unknown(self, trim: HouseTrim) -> list[str]:
        """Виды дома, которых нет в записях: none допустим, кроме двери."""
        return [f"{n}={k}" for n, k in trim if k not in getattr(self, n)
                and not (k == NONE_KIND and n != DOOR_FIELD)]


class GPTSize(Section):
    block: int
    layers: int
    heads: int
    width: int
    dropout: float


class Fit(Section):
    epochs: int
    batch: int
    lr: float
    min_lr: float
    warmup_steps: int
    weight_decay: float
    betas: tuple[float, float]
    grad_clip: float
    seed: int
    device: Device
    bf16: bool
    compile: bool
    save_every: int
    init: Path | None = None        # дообучение: веса с этого чекпойнта (gf#198)
    mix: dict[Source, int] = {}     # источник → сколько его последовательностей train подмешать
    skip_longer: bool = False       # длиннее окна модели — не учить (окно чекпойнта не растёт)


class Sampling(Section):
    """Как модель выбирает следующий токен: температура и top-k (0 — весь словарь)."""

    temperature: float
    top_k: int


class SampleRun(Sampling):
    count: int
    batch: int


class Evaluate(Section):
    count: int
    batch: int
    untrained: int


class Probe(Section):
    every: int
    count: int


class TrainPaths(Section):
    runs_dir: Path


class Train(Section):
    """Обучение модели шага 4 (config/train.toml, gf#106)."""

    model: GPTSize
    fit: Fit
    sample: SampleRun
    eval: Evaluate
    probe: Probe
    paths: TrainPaths


class RealismReference(Section):
    """С какими домами сравнивается правдоподобие ответа в «лучшем из N» (gf#213)."""

    source: Source
    split: Split


class LayoutModel(Sampling):
    checkpoint: Path
    attempts: int
    best_of: int = Field(ge=1)
    wall_retry: bool
    seed: int
    device: Device
    bf16: bool
    constrain: bool
    reference: RealismReference


class FinishColor(Section):
    """Цвет из ряда цветов отделки; words — слова текста, которыми его просят. Нет hex —
    у материала нет своего цвета, он берёт цвет вида из библиотеки (`facade: Цвет вида по
    умолчанию`)."""

    hex: str | None = Field(default=None, pattern=r"^#[0-9a-f]{6}$")
    words: list[str] = []


class FinishRole(Section):
    """Материал роли палитры в отделке: вид из library.toml и ряд цветов (первый — по умолчанию).
    extra — цвета, которые только просят словом: от текста без слов они не выпадают."""

    kind: str
    colors: list[str] = Field(min_length=1)
    extra: list[str] = []


class Scheme(Section):
    """Сочетание цветов из источника (gf#317): цвета ролей палитры по именам из ряда colors;
    source — откуда взято. Роли, которых нет, берут ряд отделки."""

    source: str
    colors: dict[PaletteRole, str]

    @model_validator(mode="after")
    def _has_main(self) -> Self:
        if PaletteRole.MAIN not in self.colors:
            raise ValueError("сочетание без цвета стен (main)")
        return self


class Finish(Section):
    """Отделка дома: материалы палитры по ролям и виды выводимых элементов (gf#303);
    styles — стили раскладки, с которыми она сочетается."""

    styles: list[str] = Field(min_length=1)
    trim: HouseTrim
    roof: RoofKind  # вид крыши отделки, если в тексте его нет (gf#320)
    materials: dict[PaletteRole, FinishRole]
    schemes: list[str] = []  # сочетания цветов, которые отделка берёт от текста (gf#317)


class SkylightWords(Section):
    words: list[str]                       # слова текста: мансардные окна
    default: int = Field(ge=1)             # окон на скат, если текст их называет


class DormerStub(Section):
    """Дормеры стаба шага 1 (gf#457, `generation: Слуховые окна по словам текста`): слова текста,
    лицо и вид крыши по умолчанию, скаты, когда плана ещё нет (карнизы вдоль x: двускатный дом по
    умолчанию — карнизные стены смотрят на ±y). С планом — `dormers.on_eaves`."""

    words: list[str]
    width_m: float = Field(gt=0)
    roof: DormerRoof
    facings: list[Facing]


class SpecStub(Section):
    default_finish: str                    # отделка дома без описания
    stem_tail: int                         # букв после основы, при которых слово совпало
    reach: int                             # слов от цвета до слова, чью роль он красит
    negations: list[str]                   # слово перед названием элемента — элемента нет
    floors_words: dict[int, list[str]]     # этажей → слова в тексте
    wing_words: dict[int, list[str]]       # этажей у нижних частей дома → слова в тексте (gf#322)
    style_words: dict[str, list[str]]      # стиль → слова в тексте
    material_words: dict[str, list[str]]   # вид стен из библиотеки → слова в тексте
    material_like: dict[str, str] = {}     # вид → общий вид: слова общего называют и этот вид
    trim_words: dict[Trim, list[str]]      # выводимый элемент → слова в тексте
    dormer: DormerStub                     # слуховые окна: слова, лицо, вид крыши (gf#457)
    kind_words: dict[str, dict[str, list[str]]]  # элемент → вид (derive.toml) → слова в тексте
    roof_words: dict[RoofKind, list[str]]  # вид крыши → слова в тексте (gf#320)
    entrance_gable_words: list[str]        # слова «щипец над входом» (gf#455)
    skylights: SkylightWords               # мансардные окна по словам текста (gf#456)
    roof_shape: RoofShape                  # уклон и свес по виду крыши — и синтетике
    chimney_words: list[str]               # слова трубы, печи, камина (gf#454); «без» — трубы нет
    chimney_at: float = Field(ge=0, le=1)  # место трубы по умолчанию — доля длины конька
    gutter_words: list[str]                # слова водостока; «без» (negations) — водостока нет
    gutters_default: bool                  # слов нет — водосток есть или нет
    role_words: dict[PaletteRole, list[str]]  # роль палитры → слова, перед которыми цвет её красит
    trim_default: HouseTrim                # вид названного в тексте элемента, если его нет
    colors: dict[str, FinishColor]         # ряд цветов отделки по имени
    schemes: dict[str, Scheme] = {}        # сочетания цветов из источников (gf#317)
    finish: dict[str, Finish]              # библиотека отделок

    @model_validator(mode="after")
    def _check(self) -> "SpecStub":
        """Опечатка в имени отделки или цвета — ошибка загрузки, а не молчаливый отказ."""
        if self.default_finish not in self.finish:
            raise ValueError(f"default_finish: нет отделки {self.default_finish}")
        for name, finish in self.finish.items():
            if set(finish.materials) != set(PaletteRole):
                raise ValueError(f"отделка {name}: роли {sorted(finish.materials)}, "
                                 f"а нужны {sorted(PaletteRole)}")
            used = {c for m in finish.materials.values() for c in [*m.colors, *m.extra]}
            unknown = used - set(self.colors)
            if unknown:
                raise ValueError(f"отделка {name}: нет цветов в ряду colors — {sorted(unknown)}")
            self._check_schemes(name, finish)
            if styles := set(finish.styles) - set(self.style_words):
                raise ValueError(f"отделка {name}: нет стилей в style_words — {sorted(styles)}")
        return self

    def _check_schemes(self, name: str, finish: Finish) -> None:
        """Сочетание отделки — из ряда colors, а цвет стен — из тех, что у отделки на стенах."""
        main = finish.materials[PaletteRole.MAIN]
        for scheme in finish.schemes:
            if scheme not in self.schemes:
                raise ValueError(f"отделка {name}: нет сочетания {scheme}")
            colors = self.schemes[scheme].colors
            if unknown := set(colors.values()) - set(self.colors):
                raise ValueError(f"сочетание {scheme}: нет цветов в colors — {sorted(unknown)}")
            if colors[PaletteRole.MAIN] not in [*main.colors, *main.extra]:
                raise ValueError(f"{name}: цвет стен сочетания {scheme} не из рядов")

    def kinds(self) -> set[str]:
        """Виды материалов, которые называет стаб: в отделках и в словах вида стен."""
        return {m.kind for f in self.finish.values() for m in f.materials.values()} \
            | set(self.material_words) | self.material_like.keys() \
            | set(self.material_like.values())


class Models(Section):
    """Модели шагов конвейера (config/models.toml, gf#107)."""

    spec: SpecStub
    layout: LayoutModel


class Svd(Section):
    px_per_m: float
    k_max: int


class Calibrate(Section):
    reference: int


class Visual(Section):
    px_per_m: float
    canvas_m: tuple[float, float]
    batch: int
    device: Device
    kid_subset: int
    kid_subsets: int
    background: str
    colors: dict[ElementClass, str]  # опечатка в классе элемента — ошибка загрузки


class Realism(Section):
    k: int
    subsets: int
    house_score: HouseScore  # по какой оценке дома «лучший из N» выбирает ответ
    marginal_window: float   # окно marginal: ± столько разбросов признака
    features: list[str]  # имена из metrics/wall_features.FEATURES; опечатка — ошибка при счёте
    size_tol_m: float
    axis_tol_m: float
    zone_step_m: float


class Realtest(Section):
    summary: list[str]   # колонки таблицы метрик (metrics/table.py, COLUMNS) в summary.md
    stability: list[str]  # колонки сводки по вариантам сэмплинга (metrics/stability.py)
    digits: int          # знаков после запятой в сводке по вариантам
    slices: dict[str, str]  # срез домов (gf#328): имя → источник разметки; строки `<строка>@<имя>`


class Tolerances(Section):
    """Датчик допусков tools/tolerance_probe.py (gf#403)."""

    percentiles: list[float]  # процентили распределений: допуск берётся по одному из них
    pick: float               # процентиль, предлагаемый как допуск (столбец «предварительно»)


class Metrics(Section):
    """Метрики оценки (config/metrics.toml, gf#16, gf#143, gf#210)."""

    seed: int
    pairs: int
    quantile_points: int
    svd: Svd
    realism: Realism
    calibrate: Calibrate
    visual: Visual
    realtest: Realtest
    tolerances: Tolerances


class GenPlanRule(Section):
    window: tuple[float, float]


class EvoVecRun(Section):
    code: Path         # папка EvoVec-Evolutionary-Image-Vectorization клона VGLib
    generations: int   # STEP_EVOL EvoVec
    individuals: int   # INDIVIDUAL_COUNT EvoVec


class VtracerRun(Section):
    """Параметры `vtracer.convert_image_to_svg_py` — как в библиотеке (имена те же)."""

    colormode: str
    hierarchical: str
    mode: str
    filter_speckle: int
    color_precision: int
    layer_difference: int
    corner_threshold: int
    length_threshold: float
    max_iterations: int
    splice_threshold: int
    path_precision: int


class Texture(Section):
    """Загрязнение растра: полоски обшивки и шум, чтобы растр не был идеально плоским."""

    siding_px: int      # линия обшивки на стене каждые столько строк; 0 — без линий
    siding_dim: float   # на сколько линия темнее стены, доля яркости
    noise: float        # стандартное отклонение шума по каналу, 0–255; 0 — без шума


class Vectorizer(Section):
    """Базовый подход «растр + готовый векторизатор» (config/baselines.toml, gf#17)."""

    python: Path       # интерпретатор venv со сторонними библиотеками
    worker: Path       # tools/vectorize_worker.py
    jobs: int          # процессов векторизатора разом
    long_side_px: int  # длинная сторона растра стены
    min_side_px: float  # область с меньшей стороной — крошка трассировки, не элемент
    match_iou: float   # IoU, с которого элемент векторизатора — тот же элемент эталона (damage.py)
    align_px: float    # допуск «на одной линии», пикселей растра: шаг растра ≈ 2 см
    min_visible: float  # элемент эталона, у которого на растре виден меньший цвет класса, спрятан
    hidden_path_share: float  # путь SVG, чей цвет виден на меньшей доле его рамки, закрыт
    open_radius_px: int  # полоски класса тоньше 2·этого + 1 пикселей — сглаживание края, не элемент
    texture: Texture
    evovec: EvoVecRun
    vtracer: VtracerRun
    colors: dict[ElementClass, str]  # цвет класса на растре: разведены, чтобы квантование не слило

    @model_validator(mode="after")
    def _every_class_has_color(self) -> "Vectorizer":
        if missing := set(ElementClass) - set(self.colors):
            raise ValueError(f"vectorizer.colors: нет цвета у классов {sorted(missing)}")
        return self


class LlmEndpoint(Section):
    """Один поставщик LLM: модель, переменная окружения с ключом и цена, доллары за 1 млн
    токенов. Ключ берётся из окружения по имени `key_env`, не из файла."""

    model: str
    key_env: str | None = None  # у заглушки ключа нет
    base_url: str | None = None  # OpenAI-совместимый API другого поставщика (DeepSeek)
    usd_per_mtok_in: float = Field(ge=0)
    usd_per_mtok_out: float = Field(ge=0)


class LlmPrompt(Section):
    """Слова промпта; `{…}` подставляет genfacade/llm.py."""

    instruction: str     # как читать запись и что отвечать; {grid_m} — шаг сетки
    vocabulary: str      # подпись списка служебных токенов; {words}
    example: str         # подпись примера; {n}
    house: str           # описание дома словами; {type} {floors} {roof} {style} {sides}
    mode: dict[Mode, str]  # условие режима словами
    condition: str       # подпись условия
    answer: str          # подпись ответа


class Llm(Section):
    """LLM без дообучения (gf#162): few-shot из синтетики, запись токенами, тот же разбор,
    привязка и валидатор, что у модели."""

    shots: int = Field(ge=0)       # примеров в промпте
    pool: int = Field(ge=1)        # домов синтетики train, из которых берутся ближайшие
    seed: int                      # какие дома пула и как досэмплировать
    attempts: int = Field(ge=1)    # попыток на дом, как `[layout] attempts` у модели
    temperature: float             # как у LayoutGPT и LayoutPrompter
    max_output_tokens: int = Field(ge=1)
    timeout_s: float = Field(gt=0)  # ожидание ответа поставщика: дольше — отказ, не зависание
    chars_per_token: float = Field(gt=0)  # оценка токенов для --dry-run: знаков на токен
    providers: dict[LlmProvider, LlmEndpoint]
    prompt: LlmPrompt

    @model_validator(mode="after")
    def _every_provider(self) -> Self:
        if missing := set(LlmProvider) - set(self.providers):
            raise ValueError(f"llm.providers: нет поставщиков {sorted(missing)}")
        return self


class Baselines(Section):
    """Базовые подходы (config/baselines.toml, `evaluation: Базовые подходы`)."""

    genplan: GenPlanRule
    vectorizer: Vectorizer
    llm: Llm


class GuidelineSource(Section):
    doc: str      # документ и год
    file: str     # текст источника, путь от tmp/facade-rules/ (вне git)
    where: str    # страница или пункт
    quote: str    # дословно, на языке источника
    checked: bool  # цитата найдена в тексте источника


class Guideline(Section):
    """Правило фасада из свода (gf#209): что утверждает, чем проверяется, откуда взято."""

    id: str
    text: str
    check: GuidelineCheck
    params: GuidelineParams = {}
    applies: list[Region]
    use: list[GuidelineUse] = []
    note: str = ""
    source: list[GuidelineSource]


class Guidelines(Section):
    """Свод правил фасада (config/guidelines.toml): нормы, pattern books, руководства, книги."""

    guideline: list[Guideline]


class Config(Section):
    library: Library
    sheet: Sheet
    viewer: Viewer
    plan: PlanConfig
    checks: Checks
    data: Data
    synthetic: Synthetic
    tokens: Tokens
    train: Train
    models: Models
    metrics: Metrics
    baselines: Baselines
    guidelines: Guidelines
    derive: Derive
    ifc: IfcExport
    dormer: DormerRules
    css: str

    @model_validator(mode="after")
    def _stub_kinds_in_library(self) -> "Config":
        """Вид материала стаба шага 1 — из [kinds] library.toml: опечатка — ошибка загрузки."""
        if unknown := self.models.spec.kinds() - set(self.library.kinds):
            raise ValueError(f"spec: видов нет в library.toml [kinds] — {sorted(unknown)}")
        return self

    @model_validator(mode="after")
    def _trim_kinds_in_derive(self) -> "Config":
        """Виды выводимых элементов в отделках, весах синтетики и ручной разметке — записи
        derive.toml, слова вида в тексте — тоже: опечатка — ошибка загрузки (gf#318)."""
        houses = {f"отделка {n}": f.trim for n, f in self.models.spec.finish.items()}
        houses |= {"trim_default": self.models.spec.trim_default,
                   "manual": self.data.manual.trim}
        bad = {n: u for n, t in houses.items() if (u := self.derive.unknown(t))}
        weights = self.synthetic.facade.trim
        bad |= {f"вес {n}": missing for n, w in weights
                if (missing := [k for k in w if k not in self.derive.kinds(n)
                                and not (k == NONE_KIND and n != DOOR_FIELD)])}
        words = self.models.spec.kind_words
        bad |= {f"слова {n}": missing for n, kw in words.items()
                if (missing := [k for k in kw if k not in self.derive.kinds(n)])}
        if bad:
            raise ValueError(f"виды, которых нет в config/derive.toml: {bad}")
        return self


def load(*user_dirs: Path) -> Config:
    """Умолчания пакета, поверх — файлы из user_dirs по порядку: следующая папка перекрывает
    предыдущую (своя папка машины, поверх — настройки одного этапа, tools/retrain.sh)."""
    css = DEFAULTS.joinpath("sheet.css").read_text()
    for folder in user_dirs:
        if (folder / "sheet.css").exists():
            css += "\n" + (folder / "sheet.css").read_text()
    guidelines = Guidelines(**_toml("guidelines.toml", user_dirs))
    norms = {g.check: g.params for g in guidelines.guideline if GuidelineUse.VALIDATE in g.use}
    return Config(
        library=Library(**_toml("library.toml", user_dirs)),
        sheet=Sheet(**_toml("sheet.toml", user_dirs)),
        viewer=Viewer(**_toml("viewer.toml", user_dirs)),
        plan=PlanConfig(**_toml("plan.toml", user_dirs)),
        checks=Checks(**_toml("checks.toml", user_dirs), norms=norms),
        data=Data(**_toml("data.toml", user_dirs)),
        synthetic=Synthetic(**_toml("synthetic.toml", user_dirs)),
        tokens=Tokens(**_toml("tokens.toml", user_dirs)),
        train=Train(**_toml("train.toml", user_dirs)),
        models=Models(**_toml("models.toml", user_dirs)),
        metrics=Metrics(**_toml("metrics.toml", user_dirs)),
        baselines=Baselines(**_toml("baselines.toml", user_dirs)),
        guidelines=guidelines,
        derive=Derive(**_toml("derive.toml", user_dirs)),
        ifc=Ifc(**_toml("ifc.toml", user_dirs)).ifc,
        dormer=DormerRules(**_toml("dormer.toml", user_dirs)),
        css=css,
    )


def _toml(name: str, user_dirs: tuple[Path, ...]) -> dict:
    data = tomllib.loads(DEFAULTS.joinpath(name).read_text())
    for folder in user_dirs:
        if (folder / name).exists():
            _merge(data, tomllib.loads((folder / name).read_text()))
    return data


def _merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
