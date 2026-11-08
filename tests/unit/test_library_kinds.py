"""Библиотека материалов (gf#317, `facade: Цвет вида по умолчанию`, `Рисунок материала`): каждый
вид из `[kinds]` рисуется на листе и в 3D, а новый вид — это записи в конфиге, не код."""

import re

import pytest
from sheets import with_kind

from genfacade import config
from genfacade.render.house3d import house_3d
from genfacade.render.svg import sheet_svg
from genfacade.schema import Mode
from genfacade.train import tokens

KINDS = list(config.load().library.kinds)
ROLES = ("main", "plinth", "roof")
PATTERN_URL = re.compile(r'fill="url\(#hatch-([a-z0-9_]+)-[0-9a-f]{6}\)"')


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_is_drawn_on_sheet_and_in_3d(house, cfg, kind, role):
    """Лист и 3D строятся с любым видом в любой роли; рисунок — ровно у видов из [patterns]."""
    sheet = with_kind(house, role, kind)
    svg = sheet_svg(sheet, cfg)
    walls = house_3d(sheet, cfg)["walls"]
    assert walls
    used = set(PATTERN_URL.findall(svg))
    if role != "roof":  # крыша на листе рисуется скатами, зон материала у неё нет
        assert (kind in used) == (kind in cfg.library.patterns)


def test_default_colors_are_hex_and_model_kinds_are_known(cfg):
    lib = cfg.library
    assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in lib.kinds.values())
    assert set(lib.model_kinds.values()) <= set(lib.kinds) - set(lib.model_kinds)


def test_new_kind_is_added_by_records_only(tmp_path, house, cfg):
    """Вид, добавленный записями в library.toml, рисуется на листе и в 3D, а словарь модели
    шага 4 (его чекпойнт) не меняется."""
    (tmp_path / "library.toml").write_text(
        '[kinds]\nmarble = "#e0e0e8"\n[model_kinds]\nmarble = "stone"\n'
        "[patterns.marble]\nvertical = false\nline_m = 0.01\ngroove_m = 0.0\nwidth_m = 0.6\n"
        "courses = [{ h_m = 0.3, joints_m = [0.3] }]\n")
    extended = config.load(tmp_path)
    sheet = with_kind(house, "main", "marble")
    assert "hatch-marble-" in sheet_svg(sheet, extended)
    assert house_3d(sheet, extended)["walls"]
    assert tokens.vocabulary(extended) == tokens.vocabulary(cfg)
    assert "kind:stone" in tokens.condition(sheet, Mode.BLIND, extended)


def test_model_kind_must_point_at_a_known_untranslated_kind(tmp_path):
    (tmp_path / "library.toml").write_text('[model_kinds]\nbrick = "nowhere"\n')
    with pytest.raises(ValueError, match="model_kinds"):
        config.load(tmp_path)
