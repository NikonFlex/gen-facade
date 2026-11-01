"""Настройки, вынесенные из кода: материалы, лист, смотрелка, план, проверка, данные,
синтетика, токены, обучение, модели.

По умолчанию — файлы этой папки. Свой конфиг — папка с любыми из тех же файлов:
TOML сливается с умолчаниями поключно, sheet.css дописывается после умолчаний
(правила CSS переопределяют предыдущие). Опечатка в ключе — ошибка, а не молчание.
Здесь только настройки приложения; данные заглушек моделей — в genfacade/models/.
"""

import tomllib
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from genfacade.datasets.buildingnet.mesh import Label
from genfacade.schema import (
    CanopyKind,
    CasingKind,
    Device,
    ElementClass,
    GuidelineCheck,
    GuidelineUse,
    HouseScore,
    HouseTrim,
    Mode,
    PaletteRole,
    Region,
    ShutterKind,
    SillKind,
    Source,
    Split,
    VariantKind,
    ZoneRole,
)

DEFAULTS = files(__package__)


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Fill(Section):
    wall: str
    glass: str
    other: str


class Library(Section):
    kinds: dict[str, str]
    fill: Fill
    class_fill: dict[ElementClass, str]  # опечатка в классе элемента — ошибка загрузки


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


class Sheet(Section):
    sheet: SheetLayout
    ground: Ground
    levels: Levels
    axes: Axes
    door: DoorLook
    trim: TrimLook
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


class PlanConfig(Section):
    gaps: Gaps
    outline: Outline


GuidelineParams = dict[str, ElementClass | float | list[float]]


class Checks(Section):
    """Шаг 5: допуски привязки и валидатора (config/checks.toml); norms — параметры правил свода
    с `use = ["validate"]` по виду проверки (gf#242): их не пишут в checks.toml, их кладёт `load`
    из guidelines.toml — число нормы в одном месте."""

    eps_m: float
    align_m: float
    snap_m: float
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


class Labels(Section):
    """Подписи смотрелки к значениям enum из schema.py: страница берёт их отсюда."""

    mode: dict[Mode, ModeLabel]
    cls: dict[ElementClass, str]
    role: dict[ZoneRole, str]
    variant: dict[VariantKind, str]


class SamplesView(Section):
    shown: int


class House3d(Section):
    """Дом объёмом в смотрелке: откуда three.js, разрешение текстур фасадов, цвета сцены."""

    three_url: str
    px_per_m: int
    roof: str
    ground: str
    background: str
    edges: str


class Viewer(Section):
    server: Server
    paths: ViewerPaths
    samples: SamplesView
    house3d: House3d
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


class Manual(Section):
    """Ручная разметка реальных коттеджей (config/data.toml, `data: Реальные коттеджи — тест`)."""

    paths: ManualPaths
    length_tol_m: float
    wall_m: float
    inside_share: float
    link_tol_m: float
    trim: HouseTrim


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


class SpecRules(Section):
    floors_weights: list[float]
    grid_m: float
    styles: list[str]
    palette: dict[PaletteRole, list[str]]  # виды — из library.toml


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

    sill: dict[SillKind, float]
    casing: dict[CasingKind, float]
    shutters: dict[ShutterKind, float]
    canopy: dict[CanopyKind, float]


class Finish(Section):
    weights: dict[str, float]  # ключи — схемы отделки (datasets/synthetic/zones.py, Scheme)
    entrance_pad_m: float
    wainscot_m: Range
    corner_m: float
    pier_max_m: float


class Entry(Section):
    porch_p: float
    porch_pad_m: float


class FacadeRules(Section):
    windows: Windows
    door: Door
    trim: TrimWeights
    cornice: Cornice
    finish: Finish
    entry: Entry


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
    spec: SpecRules
    facade: FacadeRules


class Tokens(Section):
    """Запись дома токенами (config/tokens.toml)."""

    grid_m: float
    max_m: float


class SillLook(Section):
    overhang_m: float
    height_m: float


class ShutterLook(Section):
    share: float


class CanopyLook(Section):
    pad_m: float
    gap_m: float
    height_m: float


class CanopyKinds(Section):
    min_h_m: float
    flat: CanopyLook
    gable: CanopyLook
    bracket: CanopyLook

    def of(self, kind: CanopyKind) -> CanopyLook:
        return getattr(self, kind)


class Derive(Section):
    """Выводимые элементы проёма (config/derive.toml, gf#212): размеры по виду дома."""

    sill: dict[SillKind, SillLook]
    casing: dict[CasingKind, float]
    shutters: ShutterLook
    canopy: CanopyKinds


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


class SpecStub(Section):
    floors_words: dict[int, list[str]]  # этажей → слова в тексте
    style_words: dict[str, list[str]]   # стиль → слова в тексте
    trim: dict[str, HouseTrim]          # стиль → виды выводимых элементов дома


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


class GenPlanRule(Section):
    window: tuple[float, float]


class Baselines(Section):
    """Базовые подходы (config/baselines.toml, `evaluation: Базовые подходы`)."""

    genplan: GenPlanRule


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
    css: str


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
