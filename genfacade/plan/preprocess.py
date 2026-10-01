"""Шаг 2: SVG GenPlan → Plan со сторонами, проёмами и запретными зонами (plan-input.md).

Порядок — правило 4: разобрать SVG → найти разрывы → контур → проёмы по разрывам →
вход → масштаб → стороны с проёмами и запретными зонами. Считаем в пикселях с осью y
вверх; в метры переводим в конце, когда известен вход.
"""

from dataclasses import dataclass
from pathlib import Path

from shapely import LinearRing, box

from genfacade.config import PlanConfig
from genfacade.plan import sides
from genfacade.plan.gaps import Gap, find_gaps
from genfacade.plan.genplan_svg import TOL_PX, Box, DoorSwing, GenPlanSvg, PlanError, parse
from genfacade.plan.outline import outline
from genfacade.schema import Mode, Plan, PlanOpening, Rect

# Масштаб GenPlan: ширина входной двери — 90 см (three_dimensional/convertor.py:32,
# DEFAULT_DOOR_WIDTH). Протокол, а не настройка: иначе фасад разойдётся с 3D-моделью.
ENTRANCE_WIDTH_M = 0.9


@dataclass(frozen=True)
class Found:
    """Проём в пикселях: разрыв и что в нём."""

    kind: str  # window | door | entrance
    gap: Gap
    external: bool


def preprocess(svg: Path | str, mode: Mode, cfg: PlanConfig) -> Plan:
    """План GenPlan → Plan; дефектный план — PlanError с причиной (правило 7)."""
    raw = flip(parse(svg))
    gaps = find_gaps(raw.walls, cfg.gaps)
    ring = outline(raw.walls + raw.windows + [g.box for g in gaps], cfg.outline)
    found = _mark_entrance(_classify(raw, gaps, ring, cfg.gaps.min_opening_px))
    entrance = next(f for f in found if f.kind == "entrance")
    contour = sides.start_at(sides.Contour(ring, cfg.outline.jog_px), entrance.gap.box)
    scale = ENTRANCE_WIDTH_M / entrance.gap.length_px
    sealed = [f for f in found if mode == "blind" and f.external and f.kind != "entrance"]
    walls = raw.walls + [f.gap.box for f in sealed]
    open_ = [f for f in found if f.external and f not in sealed]
    return Plan(
        walls=[_rect(w, scale) for w in walls],
        outline=[(x * scale, y * scale) for x, y in contour.ring],
        openings=[_opening(f, scale, f in sealed) for f in found],
        sides=sides.build(contour, open_, walls, scale),
        scale_m_per_px=scale,
        source="genplan",
    )


def flip(raw: GenPlanSvg) -> GenPlanSvg:
    """Оси SVG (y вниз) → оси плана (y вверх от низа холста)."""
    h = raw.height

    def fb(b: Box) -> Box:
        return Box(b.x0, h - b.y1, b.x1, h - b.y0)

    doors = [DoorSwing((d.hinge[0], h - d.hinge[1]), (d.jamb[0], h - d.jamb[1])) for d in raw.doors]
    return GenPlanSvg(raw.width, h, [fb(w) for w in raw.walls], [fb(w) for w in raw.windows], doors)


def _classify(raw: GenPlanSvg, gaps: list[Gap], ring: list, min_px: float) -> list[Found]:
    """Разрыв со створкой — дверь; наружный без створки — окно, как у GenPlan; швы — мимо."""
    boundary = LinearRing(ring)
    found = []
    for g in gaps:
        if g.length_px < min_px:
            continue
        external = box(g.box.x0, g.box.y0, g.box.x1, g.box.y1).distance(boundary) <= TOL_PX
        is_door = any(g.box.contains(d.hinge) and g.box.contains(d.jamb) for d in raw.doors)
        if is_door or external:
            found.append(Found("door" if is_door else "window", g, external))
    return found


def _mark_entrance(found: list[Found]) -> list[Found]:
    """Вход — самая узкая наружная дверь, а без дверей — самый узкий наружный разрыв (правило 5)."""
    outer = [f for f in found if f.external]
    doors = [f for f in outer if f.kind == "door"]
    if not outer:
        raise PlanError("нет входа: на наружном контуре ни одного разрыва")
    entrance = min(doors or outer, key=lambda f: f.gap.length_px)
    return [Found("entrance", f.gap, True) if f is entrance else f for f in found]


def _rect(b: Box, scale: float) -> Rect:
    return Rect(x0_m=b.x0 * scale, y0_m=b.y0 * scale, x1_m=b.x1 * scale, y1_m=b.y1 * scale)


def _opening(f: Found, scale: float, sealed: bool) -> PlanOpening:
    rect = _rect(f.gap.box, scale)
    return PlanOpening(kind=f.kind, rect=rect, external=f.external, sealed=sealed)
