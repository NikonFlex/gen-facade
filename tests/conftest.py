import json
from pathlib import Path

import pytest

from genfacade import config
from genfacade.layout.rule import LayoutContext, place_all
from genfacade.pipeline import walls
from genfacade.plan.preprocess import preprocess
from genfacade.schema import FacadeSheet, HouseSpec
from genfacade.unfold import unfold

FIXTURES = {p.stem: p for p in sorted((Path(__file__).parent / "fixtures").glob("house_*.json"))}


def _load(name: str) -> FacadeSheet:
    return FacadeSheet.model_validate_json(FIXTURES[name].read_text())


@pytest.fixture(params=sorted(FIXTURES))
def house(request) -> FacadeSheet:
    """Каждый тестовый дом по очереди."""
    return _load(request.param)


@pytest.fixture
def load_house():
    """Тестовый дом по имени: house_gable, house_hip, house_flat."""
    return _load


@pytest.fixture
def raw_house() -> dict:
    """Двускатный дом как словарь — портить поля в тестах схемы."""
    return json.loads(FIXTURES["house_gable"].read_text())


@pytest.fixture(scope="session")
def cfg() -> config.Config:
    """Настройки пакета по умолчанию."""
    return config.load()


@pytest.fixture
def unfold_sheet(cfg):
    """Развёртка с настройками по умолчанию: дом или его имя → дом с силуэтами."""
    def run(sheet: FacadeSheet | str) -> FacadeSheet:
        house = _load(sheet) if isinstance(sheet, str) else sheet
        return unfold(house, cfg.library.roof.thickness_m)

    return run


WallPx = tuple[float, float, float, float]  # x0, y0, x1, y1 в пикселях SVG, y вниз


def _genplan_svg(walls: list[WallPx], windows: list[WallPx] = (), extra: str = "") -> str:
    """SVG в формате GenPlan: чёрные стены, голубые окна; extra — например, дуга двери."""
    def rect(r: WallPx, fill: str) -> str:
        x0, y0, x1, y1 = r
        return f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="{fill}" />'

    body = "".join(rect(w, "#000000") for w in walls) + "".join(rect(w, "#99ccff") for w in windows)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" '
            f'viewBox="0 0 600 600">{body}{extra}</svg>')


BOX_LO, BOX_HI, BOX_WALL = 100, 500, 15  # коробка синтетических планов, пиксели


def _box_walls(gaps: dict[str, list[tuple[float, float]]]) -> list[WallPx]:
    """Стены коробки; gaps — разрывы (от, до) на сторонах top, bottom, left, right."""
    lo, hi, t = BOX_LO, BOX_HI, BOX_WALL
    lines = {"top": (lo, lo + t, "x"), "bottom": (hi - t, hi, "x"),
             "left": (lo, lo + t, "y"), "right": (hi - t, hi, "y")}
    walls = []
    for side, (c0, c1, axis) in lines.items():
        cuts = [lo, *[v for g in sorted(gaps.get(side, [])) for v in g], hi]
        for a, b in zip(cuts[::2], cuts[1::2], strict=True):
            if b > a:  # разрыв во всю сторону — стены нет
                walls.append((a, c0, b, c1) if axis == "x" else (c0, a, c1, b))
    return walls


@pytest.fixture
def preprocess_svg(cfg):
    """Препроцессор с настройками по умолчанию: текст SVG или путь → Plan."""
    def run(svg, mode="with_openings"):
        return preprocess(svg, mode, cfg.plan)

    return run


@pytest.fixture
def box_svg():
    """SVG коробки 100..500 px: разрывы по сторонам, окна, внутренние стены, что-то ещё."""
    def make(gaps: dict, windows: list[WallPx] = (), inner: list[WallPx] = (),
             extra: str = "") -> str:
        return _genplan_svg(_box_walls(gaps) + list(inner), windows, extra)

    return make


SPECS = Path(__file__).parent / "fixtures" / "specs"
# Вариант дома для тестов раскладки: файл HouseSpec из SPECS (None — config/house.json)
# и уровень высоты окон (None — из config/layout.toml).
VARIANTS = {
    "house": (None, None),
    "small_windows": (None, "small"),
    "high_windows": (None, "high"),
    "modern_flat": ("modern_flat", None),
    "modern_panoramic": ("modern_flat", "high"),
    "three_hip": ("three_hip", "small"),
}


@pytest.fixture
def lay_out(cfg):
    """План → стены после развёртки и раскладки правилом: шаги 2–4 без трассы."""
    def run(svg, variant: str = "house", mode: str = "with_openings", seed: int = 0) -> FacadeSheet:
        house, rule = _variant(cfg, variant)
        plan = preprocess(svg, mode, cfg.plan)
        return place_all(walls(house, plan, cfg), LayoutContext(house, mode, "", seed), rule)

    return run


def _variant(cfg, name: str):
    spec, level = VARIANTS[name]
    house = cfg.house if spec is None else HouseSpec.model_validate_json(
        (SPECS / f"{spec}.json").read_text())
    windows = cfg.layout.windows.model_copy(update={"level": level or cfg.layout.windows.level})
    return house, cfg.layout.model_copy(update={"windows": windows})
