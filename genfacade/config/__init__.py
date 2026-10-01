"""Настройки, вынесенные из кода: материалы, лист, смотрелка, план, проверка, данные,
синтетика.

По умолчанию — файлы этой папки. Свой конфиг — папка с любыми из тех же файлов:
TOML сливается с умолчаниями поключно, sheet.css дописывается после умолчаний
(правила CSS переопределяют предыдущие). Опечатка в ключе — ошибка, а не молчание.
Здесь только настройки приложения; данные заглушек моделей — в genfacade/models/.
"""

import tomllib
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from genfacade.schema import ElementClass, Mode, PaletteRole, VariantKind, ZoneRole

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


class Sheet(Section):
    sheet: SheetLayout
    ground: Ground
    levels: Levels
    axes: Axes
    title: Title
    preview: Preview
    plan: PlanLook


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


class Data(Section):
    """Данные для обучения и теста (config/data.toml, specs/data.md)."""

    paths: DataPaths


Range = tuple[float, float]


class Canvas(Section):
    px_per_m: int
    margin_m: float


class HouseSize(Section):
    width_m: Range
    depth_m: Range
    grid_m: float
    wall_m: float


class OpeningRules(Section):
    grid_m: float
    corner_clear_m: float
    between_m: float
    window_widths_m: list[float]
    widths_per_house: int
    per_bay_weights: list[float]
    entrance_long_p: float
    blind_long_p: float
    blind_short_p: float


class Partitions(Section):
    max_count: int
    min_room_m: float
    passage_m: float


class SpecRules(Section):
    floor_heights_m: list[float]
    plinth_m: Range
    grid_m: float
    styles: list[str]
    palette: dict[PaletteRole, list[str]]  # виды — из library.toml


class Windows(Section):
    size: dict[str, Range]
    weights: dict[str, float]
    sash_max_w_m: float
    transom_min_h_m: float
    lintel_m: float


class Height(Section):
    height_m: float


class Sill(Section):
    overhang_m: float
    height_m: float


class Casing(Section):
    styles: list[str]
    width_m: float


class Accent(Section):
    p: float
    pad_m: float


class FacadeRules(Section):
    windows: Windows
    door: Height
    sill: Sill
    casing: Casing
    cornice: Height
    accent: Accent


class Synthetic(Section):
    """Генератор синтетических домов (config/synthetic.toml, specs/data.md, правило 1)."""

    canvas: Canvas
    house: HouseSize
    openings: OpeningRules
    partitions: Partitions
    spec: SpecRules
    facade: FacadeRules


class Config(Section):
    library: Library
    sheet: Sheet
    viewer: Viewer
    plan: PlanConfig
    checks: Checks
    data: Data
    synthetic: Synthetic
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
