"""Трасса шага 2: картинка плана и её легенда (render/plan_svg.py, gf#66)."""

import re
from xml.etree import ElementTree

import pytest

from genfacade import config
from genfacade.render.plan_svg import plan_svg

LEAF = '<rect x="800" y="495" width="5" height="90" fill="#000000" />'
INNER = '<rect x="500" y="115" width="10" height="285" fill="#000000" />'  # даёт запретную зону
COLOR_WORDS = re.compile(r"зел[её]н|голуб|красн|оранж|коричн|сер(ый|ая)|син", re.IGNORECASE)


@pytest.fixture
def plan_tree(preprocess_svg, simple_svg, cfg):
    """План простого дома в глухом режиме с внутренней стеной: на нём есть все классы."""
    plan = preprocess_svg(simple_svg((LEAF, INNER + LEAF)), mode="blind")
    return ElementTree.fromstring(plan_svg(plan, cfg))


def _classes(nodes) -> set[str]:
    return {n.get("class") for n in nodes if n.get("class", "").startswith("plan-")}


def _legend(tree):
    return next(g for g in tree.findall(".//{*}g") if g.get("class") == "plan-legend-box")


def test_every_drawn_class_has_legend_entry(plan_tree):
    drawing = next(g for g in plan_tree.findall(".//{*}g") if g.get("transform"))
    drawn = _classes(drawing.iter()) - {"plan-outline"}
    assert drawn == {"plan-wall", "plan-entrance", "plan-sealed", "plan-forbidden"}
    assert drawn <= _classes(_legend(plan_tree).iter())
    # и тот же вид фигуры: запретная зона — линия, у её класса в CSS нет заливки
    shape = {n.get("class"): _tag(n) for n in drawing.iter() if n.get("class") in drawn}
    assert all(_tag(n) == shape[n.get("class")] for n in _legend(plan_tree)
               if n.get("class") in drawn)


def _tag(node) -> str:
    return node.tag.rsplit("}", 1)[-1]


def test_legend_swatches_take_color_only_from_css(plan_tree, cfg):
    """Образец — тот же класс, что на чертеже, без своего fill/stroke: цвет живёт в одном месте."""
    swatches = [n for n in _legend(plan_tree) if n.tag.endswith(("rect", "line"))]
    assert [n.get("class") for n in swatches] == [f"plan-{k}" for k in cfg.sheet.plan.legend]
    assert all(n.get("fill") is None and n.get("stroke") is None for n in swatches)


def test_legend_labels_from_config_without_color_names(plan_tree, cfg):
    labels = [n.text for n in _legend(plan_tree) if n.tag.endswith("text")]
    assert labels == list(cfg.sheet.plan.legend.values())
    assert not any(COLOR_WORDS.search(t or "") for t in plan_tree.itertext())


def test_user_label_replaces_default(tmp_path, preprocess_svg):
    (tmp_path / "sheet.toml").write_text('[plan.legend]\nentrance = "главный вход"\n')
    tree = ElementTree.fromstring(plan_svg(preprocess_svg(), config.load(tmp_path)))
    assert "главный вход" in [n.text for n in _legend(tree) if n.tag.endswith("text")]
