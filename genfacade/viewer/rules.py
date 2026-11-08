"""Страница «Правила» (gf#356, хозяин 08.11): свод правил и инварианты шага 5 — у каждого число из
конфига, источник и картинка «так / не так».

Число берёт сервер: из checks.toml (допуски привязки и валидатора) или из параметров правила свода
(guidelines.toml); страница чисел не хранит. Картинка — стена тем же render/svg.py, что рисует лист
(образцы каталога, viewer/samples.py): проём стоит на расстоянии «число × good» или «число × bad».
"""

from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Response

from genfacade.config import Config, RuleItem
from genfacade.schema import (
    Element,
    ElementClass,
    HouseSpec,
    Refusal,
    RuleDraw,
    RuleFrom,
    RuleVariant,
    refusal_record,
)
from genfacade.viewer import samples

TOP = 2  # этаж, на котором стоят верхние окна картинок с двумя этажами


def value(item: RuleItem, cfg: Config) -> float:
    """Число правила: из допуска шага 5 или из параметра правила свода."""
    if item.number_from is RuleFrom.CHECKS:
        return getattr(cfg.checks, item.key)
    return float(_guideline(item, cfg).params[item.key])


def _guideline(item: RuleItem, cfg: Config):
    return next(g for g in cfg.guidelines.guideline if g.id == item.guideline)


def listing(cfg: Config) -> list[dict]:
    result = []
    for item in cfg.viewer.rules.item:
        found = _guideline(item, cfg) if item.guideline else None
        result.append({
            "id": item.id, "title": item.title, "text": item.text, "holds": item.holds,
            "value": value(item, cfg), "unit": item.unit,
            "guideline": item.guideline, "rule": found.text if found else None,
            "sources": [s.model_dump() for s in found.source] if found else [],
            "images": [{"url": f"/api/rules/{item.id}/{v.value}.svg", "good": v is RuleVariant.GOOD,
                        "caption": cfg.viewer.rules.captions[v]} for v in RuleVariant],
        })
    return result


def image(item: RuleItem, variant: RuleVariant, cfg: Config) -> str:
    """Стена правила: значение на картинке = число × good (так) или × bad (не так)."""
    look = cfg.viewer.rules.sheet
    at = value(item, cfg) * (item.good if variant is RuleVariant.GOOD else item.bad)
    spec, elements = _DRAW[item.draw](cfg, at)
    view = samples.View(spec, (look.wall_m, look.depth_m), openings=tuple(elements))
    return samples.render(cfg, view)


def api(app: FastAPI, cfg: Config) -> None:
    @app.get("/api/rules")
    def rules() -> list[dict]:
        return listing(cfg)

    @app.get("/api/rules/{rule_id}/{variant}.svg")
    def picture(rule_id: str, variant: RuleVariant) -> Response:
        found = next((i for i in cfg.viewer.rules.item if i.id == rule_id), None)
        if found is None:
            raise HTTPException(404, refusal_record(Refusal.NO_RULE, rule_id))
        return Response(image(found, variant, cfg), media_type="image/svg+xml")


# ——— сборка стены по виду правила: (настройки, значение) → (дом, проёмы) ———

def _opening(name: str, cls: ElementClass, box: tuple[float, ...],
             floor: int = 1) -> Element:
    x, y, w, h = box
    return Element(id=name, cls=cls, x_m=round(x, 3), y_m=round(y, 3), w_m=w, h_m=h, floor=floor)


def _window(cfg: Config, name: str, x: float, y: float | None = None, floor: int = 1) -> Element:
    look = cfg.viewer.rules.sheet
    base = samples.default_spec(cfg)
    bottom = base.plinth_m + (floor - 1) * base.floor_heights_m[0]
    w, h = look.window_m
    return _opening(name, ElementClass.WINDOW,
                    (x, bottom + look.sill_m if y is None else y, w, h), floor)


def _door(cfg: Config, name: str, x: float, w: float | None = None, h: float | None = None
          ) -> Element:
    look, spec = cfg.viewer.rules.sheet, samples.default_spec(cfg)
    return _opening(name, ElementClass.DOOR,
                    (x, spec.plinth_m, w or look.door_m[0], h or look.door_m[1]))


def _one_floor(cfg: Config, elements: list[Element]) -> tuple[HouseSpec, list[Element]]:
    return samples.default_spec(cfg), elements


def _two_floors(cfg: Config, elements: list[Element]) -> tuple[HouseSpec, list[Element]]:
    spec = samples.default_spec(cfg)
    height = spec.floor_heights_m[0]
    return spec.model_copy(update={
        "floors": TOP, "floor_heights_m": [height] * TOP,
        "eaves_m": round(spec.plinth_m + height * TOP, 3)}), elements


def _corner(cfg: Config, at: float):
    return _one_floor(cfg, [_window(cfg, "w1", at), _door(cfg, "d1", cfg.viewer.rules.sheet.wall_m
                                                         - cfg.viewer.rules.sheet.door_m[0] - 1.5)])


def _pier(cfg: Config, at: float):
    w = cfg.viewer.rules.sheet.window_m[0]
    return _one_floor(cfg, [_window(cfg, "w1", 1.2), _window(cfg, "w2", 1.2 + w + at)])


def _head_line(cfg: Config, at: float):
    w = cfg.viewer.rules.sheet.window_m[0]
    base = _window(cfg, "w1", 1.2)
    return _one_floor(cfg, [base, _window(cfg, "w2", 1.2 + w + 1.4, y=base.y_m + at)])


def _door_height(cfg: Config, at: float):
    return _one_floor(cfg, [_door(cfg, "d1", 2.5, h=at)])


def _door_spread(cfg: Config, at: float):
    look = cfg.viewer.rules.sheet
    return _one_floor(cfg, [_door(cfg, "d1", 1.0), _door(cfg, "d2", 1.0 + look.door_m[0] + 1.6,
                                                         h=look.door_m[1] + at)])


def _door_width(cfg: Config, at: float):
    return _one_floor(cfg, [_door(cfg, "d1", 2.5, w=at)])


def _vertical_axes(cfg: Config, at: float):
    return _two_floors(cfg, [_window(cfg, "w1", 2.0), _window(cfg, "w2", 2.0 + at, floor=TOP)])


def _head_to_eaves(cfg: Config, at: float):
    spec = samples.default_spec(cfg)
    h = cfg.viewer.rules.sheet.window_m[1]
    return _one_floor(cfg, [_window(cfg, "w1", 2.0, y=spec.eaves_m - at - h)])


_DRAW: dict[RuleDraw, Callable] = {
    RuleDraw.CORNER: _corner, RuleDraw.PIER: _pier, RuleDraw.HEAD_LINE: _head_line,
    RuleDraw.DOOR_HEIGHT: _door_height, RuleDraw.DOOR_SPREAD: _door_spread,
    RuleDraw.DOOR_WIDTH: _door_width, RuleDraw.VERTICAL_AXES: _vertical_axes,
    RuleDraw.HEAD_TO_EAVES: _head_to_eaves,
}
