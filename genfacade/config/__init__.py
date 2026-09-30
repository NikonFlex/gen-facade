"""Настройки, вынесенные из кода: библиотека материалов, оформление листа, смотрелка.

По умолчанию — файлы этой папки. Свой конфиг — папка с любыми из тех же файлов:
TOML сливается с умолчаниями поключно, sheet.css дописывается после умолчаний
(правила CSS переопределяют предыдущие). Опечатка в ключе TOML — ошибка, а не молчание.
"""

import tomllib
from importlib.resources import files
from pathlib import Path

from pydantic import BaseModel, ConfigDict

DEFAULTS = files(__package__)


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Fill(Section):
    wall: str
    roof: str
    glass: str
    other: str


class RoofLook(Section):
    thickness_m: float


class Library(Section):
    kinds: dict[str, str]
    fill: Fill
    class_fill: dict[str, str]
    roof: RoofLook


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


class Sheet(Section):
    sheet: SheetLayout
    ground: Ground
    levels: Levels
    axes: Axes
    title: Title
    preview: Preview


class Server(Section):
    host: str
    port: int


class ViewerPaths(Section):
    runs_dir: Path
    houses_dirs: list[Path]


class Viewer(Section):
    server: Server
    paths: ViewerPaths


class Config(Section):
    library: Library
    sheet: Sheet
    viewer: Viewer
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
