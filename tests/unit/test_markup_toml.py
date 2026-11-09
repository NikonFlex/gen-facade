"""Запись разметки сохраняет комментарии в конце строк (gf#348)."""

import tomllib

from genfacade.datasets import manual, markup_toml

OLD = """# шапка: происхождение
id = "t-1"
pdf = "t/sheet.pdf"
roof = "плоская"
roof_kind = "flat"
pitch_deg = 0.0
overhang_m = 0.0
unit = "m"
pt_per_unit = 100.0
material = "brick"  # светлый кирпич
plinth = 0.4  # отметки -0,4…0
floor_heights = [2.8]
cut = ["south: крыльцо",   # крыльцо не размечено
       "east: свес"]

[[sides]]
view = "юг"
page = 1
wall = [0.0, 1000.0]
floor = 900.0
elements = [
  { cls = "window", box = [100.0, 300.0, 200.0, 500.0] },   # окно 1,0 х 2,0 м
  { cls = "door", box = [700.0, 520.0, 800.0, 800.0] },  # дверь старая
]
"""


def moved(text: str) -> str:
    return text.replace("100.0, 300.0, 200.0, 500.0", "110.0, 300.0, 210.0, 500.0")


def markup_of(text: str) -> manual.Markup:
    return manual.Markup.model_validate(tomllib.loads(text))


def test_trailing_comments_stay_on_their_fields_and_unchanged_elements():
    new = markup_of(OLD.replace("700.0, 520.0", "710.0, 520.0"))
    text = markup_toml.dumps(new, markup_toml.header(OLD), OLD)
    lines = text.splitlines()
    assert any(x.startswith('material = "brick"') and x.endswith("# светлый кирпич") for x in lines)
    assert any(x.startswith("plinth = 0.4") and x.endswith("# отметки -0,4…0") for x in lines)
    assert any('"south: крыльцо"' in x and x.endswith("# крыльцо не размечено") for x in lines)
    window = "[100.0, 300.0, 200.0, 500.0]"
    assert any(window in x and x.endswith("# окно 1,0 х 2,0 м") for x in lines)
    assert markup_of(text) == new


def test_comment_of_changed_element_is_kept_as_line_above_the_side():
    new = markup_of(moved(OLD))
    text = markup_toml.dumps(new, markup_toml.header(OLD), OLD)
    lines = text.splitlines()
    assert lines[lines.index("[[sides]]") - 1] == "# окно 1,0 х 2,0 м"
    assert "# окно 1,0 х 2,0 м" not in [x[x.find("#"):] for x in lines if "{" in x]
    assert markup_of(text) == new


def test_write_reads_old_text_from_the_file(tmp_path):
    path = tmp_path / "t-1.toml"
    path.write_text(OLD)
    markup_toml.write(path, markup_of(moved(OLD)))
    assert path.read_text().startswith("# шапка: происхождение\n")
    assert "# светлый кирпич" in path.read_text()
    assert markup_of(path.read_text()) == markup_of(moved(OLD))
