import pytest
from pydantic import ValidationError

from genfacade import config
from genfacade.render.svg import sheet_svg
from genfacade.schema import FacadeSheet


def test_user_toml_overrides_one_key(tmp_path, cfg):
    (tmp_path / "sheet.toml").write_text("[levels]\noffset_m = 3.0\n")
    user = config.load(tmp_path)
    assert user.sheet.levels.offset_m == 3.0
    # остальное — из умолчаний
    assert user.sheet.levels.shelf_left_m == cfg.sheet.levels.shelf_left_m
    assert user.library == cfg.library


def test_typo_in_user_toml_rejected(tmp_path):
    (tmp_path / "sheet.toml").write_text("[levels]\nofset_m = 3.0\n")
    with pytest.raises(ValidationError, match="ofset_m"):
        config.load(tmp_path)


def test_user_css_goes_after_defaults(tmp_path, cfg):
    (tmp_path / "sheet.css").write_text(".ground { stroke-width: 0.2px; }")
    css = config.load(tmp_path).css
    assert css.startswith(cfg.css) and css.rstrip().endswith(".ground { stroke-width: 0.2px; }")


def test_material_color_from_library(raw_house, cfg, unfold_sheet):
    # В палитре дома цвет не задан — берётся цвет вида из библиотеки.
    assert raw_house["spec"]["materials"][1] == {"id": "plinth", "kind": "concrete", "color": None}
    sheet = unfold_sheet(FacadeSheet.model_validate(raw_house))
    assert f'fill="{cfg.library.kinds["concrete"]}"' in sheet_svg(sheet, cfg)


def test_unknown_kind_without_color_rejected(raw_house, cfg, unfold_sheet):
    raw_house["spec"]["materials"][1] = {"id": "plinth", "kind": "unobtainium"}
    sheet = unfold_sheet(FacadeSheet.model_validate(raw_house))
    with pytest.raises(ValueError, match="unobtainium"):
        sheet_svg(sheet, cfg)
