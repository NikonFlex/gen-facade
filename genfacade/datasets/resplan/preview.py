"""Дома ResPlan для проверки глазами: исходник рядом с планом после шага 2.

    <папка>/<id>.png         слева — слои ResPlan, справа — план после препроцессора
                             (тот же render/plan_svg.py, что рисует шаг 2 в смотрелке)
    <папка>/<id>.json        откуда картинка: дом, часть, дата, коммит
    <папка>/plans/<id>.svg   план в формате GenPlan — для списка планов смотрелки

Обе половины — в метрах, в осях плана (y вверх), классы — .plan-* из sheet.css: окно ResPlan
и окно стороны красятся одним цветом.
"""

import json
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import shapely

from genfacade.config import Config
from genfacade.datasets.resplan.convert import DOOR, FRONT_DOOR, WALL, WINDOW, Drawing, svg
from genfacade.datasets.resplan.house import House
from genfacade.pipeline import git_sha
from genfacade.render import sheet_format
from genfacade.render.plan_svg import PREFIX, plan_svg
from genfacade.render.preview import to_png
from genfacade.render.sheet_format import num
from genfacade.render.svg import canvas
from genfacade.schema import OpeningKind

PLANS = "plans"
# Слой ResPlan → класс плана: входная дверь ResPlan — «вход» плана.
LAYER_CLASS = {WALL: PREFIX + "wall", WINDOW: PREFIX + OpeningKind.WINDOW,
               DOOR: PREFIX + OpeningKind.DOOR, FRONT_DOOR: PREFIX + OpeningKind.ENTRANCE}


def write(houses: list[House], source: dict[int, dict], out: Path, cfg: Config) -> None:
    """Картинка «исходник | шаг 2», опись к ней и SVG GenPlan на каждый дом."""
    (out / PLANS).mkdir(parents=True, exist_ok=True)
    for h in houses:
        drawing = svg(source[h.resplan_id], cfg)
        (out / PLANS / f"{h.id}.svg").write_text(drawing.text)
        pair = out / f"{h.id}.svg"
        pair.write_text(side_by_side(original(source[h.resplan_id], drawing, h, cfg),
                                     plan_svg(h.plan, cfg)))
        to_png(pair, out / f"{h.id}.png", cfg.data.resplan.preview_px)
        pair.unlink()
        (out / f"{h.id}.json").write_text(json.dumps({
            "house": h.id, "resplan_id": h.resplan_id, "split": h.split,
            "left": "слои ResPlan (стены, окна, двери, входная дверь), метры, y вверх",
            "right": "план после препроцессора шага 2: стороны, проёмы, запретные зоны",
            "date": datetime.now().isoformat(timespec="seconds"), "git_sha": git_sha(),
        }, ensure_ascii=False, indent=2))


def original(plan: dict, drawing: Drawing, h: House, cfg: Config) -> str:
    """Слои ResPlan в осях плана — для сравнения с планом после шага 2."""
    layers = {k: drawing.in_plan_m(plan.get(k), h.plan.scale_m_per_px) for k in LAYER_CLASS}
    margin = cfg.sheet.plan.margin_m
    x0, y0, x1, y1 = shapely.union_all(list(layers.values())).bounds
    root = canvas(x1 - x0 + 2 * margin, y1 - y0 + 2 * margin, cfg.css)
    g = ElementTree.SubElement(root, "g", {
        "transform": f"translate({num(margin - x0)},{num(y1 + margin)}) scale(1,-1)"})
    for key, css in LAYER_CLASS.items():
        for poly in shapely.get_parts(layers[key]):
            if isinstance(poly, shapely.Polygon):
                xy = " ".join(f"{num(x)},{num(y)}" for x, y in poly.exterior.coords)
                ElementTree.SubElement(g, "polygon", {"class": css, "points": xy})
    return ElementTree.tostring(root, encoding="unicode")


def side_by_side(left: str, right: str) -> str:
    """Две картинки SVG одной высоты рядом; масштаб у каждой свой, по её viewBox."""
    outer = ElementTree.Element("svg", {"xmlns": sheet_format.SVG_NS})
    x = 0.0
    for text in (left, right):
        child = ElementTree.fromstring(text)  # noqa: S314 — свой же SVG, только что нарисован
        _, _, w, h = (float(v) for v in child.get("viewBox", "").split())
        child.attrib.update({"x": num(x), "y": "0", "width": num(w / h), "height": "1"})
        outer.append(child)
        x += w / h
    outer.set("viewBox", f"0 0 {num(x)} 1")
    return ElementTree.tostring(outer, encoding="unicode")
