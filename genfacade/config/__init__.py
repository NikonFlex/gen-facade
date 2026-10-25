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

from pydantic import BaseModel, ConfigDict

from genfacade.datasets.buildingnet.mesh import Label
from genfacade.schema import (
    Device,
    ElementClass,
    Mode,
    PaletteRole,
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


class Sheet(Section):
    sheet: SheetLayout
    ground: Ground
    levels: Levels
    axes: Axes
    door: DoorLook
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


class Checks(Section):
    """Шаг 5: допуски привязки и валидатора (config/checks.toml)."""

    eps_m: float
    align_m: float
    snap_m: float


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


class Viewer(Section):
    server: Server
    paths: ViewerPaths
    samples: SamplesView
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
    size: dict[str, Range]
    weights: dict[str, float]
    sash_max_w_m: float
    transom_min_h_m: float
    lintel_m: float
    narrow_max_w_m: float
    narrow_low: float
    wide_min_w_m: float
    wide_floor_p: float


class Height(Section):
    height_m: float


class Door(Section):
    height_m: float
    transom_m: float
    weights: dict[str, float]
    glazed_panes: tuple[int, int]


class Sill(Section):
    overhang_m: float
    height_m: float


class Casing(Section):
    styles: list[str]
    width_m: float


class Finish(Section):
    weights: dict[str, float]  # ключи — схемы отделки (datasets/synthetic/zones.py, Scheme)
    entrance_pad_m: float
    wainscot_m: Range
    corner_m: float
    pier_max_m: float


class Entry(Section):
    porch_p: float
    porch_pad_m: float
    canopy_p: float
    canopy_pad_m: float
    canopy_gap_m: float
    canopy_m: float


class FacadeRules(Section):
    windows: Windows
    door: Door
    sill: Sill
    casing: Casing
    cornice: Height
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


class LayoutModel(Sampling):
    checkpoint: Path
    attempts: int
    seed: int
    device: Device
    bf16: bool
    constrain: bool


class SpecStub(Section):
    floors_words: dict[int, list[str]]  # этажей → слова в тексте


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


class Metrics(Section):
    """Метрики оценки (config/metrics.toml, gf#16, gf#143)."""

    seed: int
    pairs: int
    quantile_points: int
    svd: Svd
    calibrate: Calibrate
    visual: Visual


class GenPlanRule(Section):
    window: tuple[float, float]


class Baselines(Section):
    """Базовые подходы (config/baselines.toml, `evaluation: Базовые подходы`)."""

    genplan: GenPlanRule


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
    css: str


def load(user_dir: Path | None = None) -> Config:
    """Умолчания пакета, поверх — файлы из user_dir, если она задана."""
    css = DEFAULTS.joinpath("sheet.css").read_text()
    if user_dir is not None and (user_dir / "sheet.css").exists():
        css += "\n" + (user_dir / "sheet.css").read_text()
    return Config(
        library=Library(**_toml("library.toml", user_dir)),
        sheet=Sheet(**_toml("sheet.toml", user_dir)),
        viewer=Viewer(**_toml("viewer.toml", user_dir)),
        plan=PlanConfig(**_toml("plan.toml", user_dir)),
        checks=Checks(**_toml("checks.toml", user_dir)),
        data=Data(**_toml("data.toml", user_dir)),
        synthetic=Synthetic(**_toml("synthetic.toml", user_dir)),
        tokens=Tokens(**_toml("tokens.toml", user_dir)),
        train=Train(**_toml("train.toml", user_dir)),
        models=Models(**_toml("models.toml", user_dir)),
        metrics=Metrics(**_toml("metrics.toml", user_dir)),
        baselines=Baselines(**_toml("baselines.toml", user_dir)),
        css=css,
    )


def _toml(name: str, user_dir: Path | None) -> dict:
    data = tomllib.loads(DEFAULTS.joinpath(name).read_text())
    if user_dir is not None and (user_dir / name).exists():
        _merge(data, tomllib.loads((user_dir / name).read_text()))
    return data


def _merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
