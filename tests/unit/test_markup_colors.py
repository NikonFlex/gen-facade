"""tools/markup_colors.py (gf#470): цвет отделки — медиана пикселей мест роли на видах листа."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from genfacade import config
from genfacade.datasets import manual
from genfacade.schema import PaletteRole

PATH = Path(__file__).resolve().parents[2] / "tools" / "markup_colors.py"
SPEC = spec_from_file_location("markup_colors", PATH)
mc = module_from_spec(SPEC)
SPEC.loader.exec_module(mc)

WALL, ACCENT, PLINTH, TRIM, ROOF = "#d9d4c8", "#8a5a3c", "#777788", "#c0a060", "#aa3322"
HOUSE = """# шапка: откуда дом
id = "st-1"
pdf = "1/sheet.pdf"
roof = "двускатная"   # комментарий поля
roof_kind = "gable"
pitch_deg = 30.0
overhang_m = 0.0
unit = "m"
pt_per_unit = 100.0
material = "siding"   # вид с чертежа
plinth_material = "brick"
trim_material = "wood"
roof_material = "metal_roof"
plinth = 0.4
floor_heights = [2.0]

[[sides]]
view = "Фасад 1"
page = 1
wall = [100.0, 300.0]
floor = 300.0
elements = [
  {{ cls = "window", box = [110.0, 110.0, 190.0, 260.0] }},
  {{ cls = "cornice", box = [100.0, 80.0, 300.0, 100.0] }},
]
zones = [{{ role = "accent", material = "stone", box = [200.0, 100.0, 300.0, 300.0] }}]
roof = [[[100.0, 79.0], [300.0, 79.0], [200.0, 20.0]]]
"""


def sheet(tmp_path: Path, plinth: str = PLINTH) -> Path:
    """Лист 400 × 400: каждая роль залита своим цветом (цоколь — plinth), поверх — линии и окно."""
    img = Image.new("RGB", (400, 400), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([100, 100, 300, 300], fill=WALL)
    d.rectangle([200, 100, 300, 300], fill=ACCENT)
    d.rectangle([100, 300, 300, 340], fill=plinth)
    d.polygon([(100, 79), (300, 79), (200, 20)], fill=ROOF)
    d.rectangle([100, 80, 300, 100], fill=TRIM)
    d.rectangle([110, 110, 190, 260], fill="#3355ff")           # окно: в основную не идёт
    for y in range(105, 300, 10):                               # штриховка и контуры чертежа
        d.line([(100, y), (200, y)], fill="black", width=1)
    (tmp_path / "1").mkdir()
    img.quantize(16).save(tmp_path / "1" / "sheet.pdf", resolution=72)  # без JPEG: цвета точные
    return tmp_path


def cfg_over(pdf_dir: Path):
    """Настройки данных, у которых листы источника stroim — в pdf_dir."""
    cfg = config.load().data.manual
    return cfg.model_copy(update={"paths": cfg.paths.model_copy(
        update={"pdf_dirs": {"stroim": pdf_dir}})})


def run(tmp_path: Path, write: bool = False) -> tuple[Path, dict]:
    markup = tmp_path / "stroim" / "st-1.toml"
    markup.parent.mkdir()
    markup.write_text(HOUSE.format())
    sheet(tmp_path)
    colors = mc.house_colors(markup, cfg_over(tmp_path), {})
    if write:
        mc.write(markup, colors)
    return markup, colors


def test_each_role_gets_the_median_of_its_places(tmp_path):
    _, colors = run(tmp_path)
    want = {PaletteRole.MAIN: WALL, PaletteRole.PLINTH: PLINTH, PaletteRole.ACCENT: ACCENT,
            PaletteRole.TRIM: TRIM, PaletteRole.ROOF: ROOF}
    assert colors == want


def test_write_keeps_the_comments_and_the_markup_reads_back(tmp_path):
    markup, colors = run(tmp_path, write=True)
    text = markup.read_text()
    assert text.startswith("# шапка: откуда дом") and "# комментарий поля" in text
    assert '# вид с чертежа\ncolors = { main = "' in text
    assert manual.read(markup).colors == colors
    mc.write(markup, {PaletteRole.MAIN: "#000000"})             # повтор заменяет, а не дублирует
    assert markup.read_text().count("colors = ") == 1


def test_role_with_too_few_pixels_is_not_written(tmp_path):
    markup, _ = run(tmp_path)
    cfg = config.load().data.manual
    m = manual.read(markup)
    pdf = tmp_path / "1" / "sheet.pdf"
    found = mc.collect(m, pdf, {})[PaletteRole.PLINTH]
    assert mc.median_color(found, cfg)
    short = cfg.model_copy(update={"colors": cfg.colors.model_copy(
        update={"min_pixels": len(found) + 1})})                # пикселей на один меньше порога
    assert mc.median_color(found, short) is None
    assert mc.collect(m.model_copy(update={"plinth": 0.0}), pdf, {})[PaletteRole.PLINTH].size == 0


@pytest.mark.parametrize("role", [PaletteRole.ROOF])
def test_no_roof_polygons_no_color(tmp_path, role):
    markup, _ = run(tmp_path)
    m = manual.read(markup)
    bare = m.model_copy(update={"sides": [m.sides[0].model_copy(update={"roof": []})]})
    assert mc.collect(bare, tmp_path / "1" / "sheet.pdf", {})[role].size == 0


def test_role_without_material_in_the_palette_is_not_written(tmp_path):
    """Крыша на листе есть, а вида кровли у дома нет — цвет разметка не приняла бы (`BadMarkup`)."""
    markup, colors = run(tmp_path)
    assert PaletteRole.ROOF in colors
    markup.write_text(markup.read_text().replace('roof_material = "metal_roof"\n', ""))
    assert PaletteRole.ROOF not in mc.house_colors(markup, cfg_over(tmp_path), {})


def test_role_painted_with_paper_is_not_written(tmp_path):
    """Линейный чертёж: место роли залито цветом бумаги — цвета на листе нет, роль не пишется."""
    markup = tmp_path / "stroim" / "st-1.toml"
    markup.parent.mkdir()
    markup.write_text(HOUSE.format())
    sheet(tmp_path, plinth="#ffffff")
    colors = mc.house_colors(markup, cfg_over(tmp_path), {})
    assert PaletteRole.PLINTH not in colors and PaletteRole.MAIN in colors
