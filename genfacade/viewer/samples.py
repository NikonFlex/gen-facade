"""Образцы каталога (gf#354, viewer/catalog.py): дом и стена, на которых рисуется каждый вид.

Рисует тот же render/svg.py, что и лист: образец — настоящий `FacadeSheet`, а не отдельная
картинка, поэтому вид в каталоге выглядит так же, как на выходе модуля. Дом — заготовка стаба
шага 1 (`models/stub_data`), размеры образца — config/viewer.toml, [catalog.sample].
"""

from dataclasses import dataclass

from genfacade import derive, unfold
from genfacade.config import Config
from genfacade.models import stub
from genfacade.render import svg
from genfacade.schema import (
    Element,
    ElementClass,
    FacadeSheet,
    HouseSpec,
    Material,
    MaterialZone,
    OpeningVariant,
    PaletteRole,
    Side,
    SideFacade,
    Trim,
    ZoneRole,
)

# Нормали сторон прямоугольника по часовой от входа (юг, запад, север, восток): так обходит
# контур развёртка (unfold.plan_corners); это протокол плана, а не настройка.
ORIENTATIONS = ((0.0, -1.0), (-1.0, 0.0), (0.0, 1.0), (1.0, 0.0))
FLOOR = 1  # образец одноэтажный


@dataclass(frozen=True)
class View:
    """Что рисовать: параметры дома, его план (длинная и короткая сторона), какая сторона в кадре
    и что на ней стоит. trims — признаки выводимых элементов у проёмов, которые выведет код."""

    spec: HouseSpec
    plan: tuple[float, float]
    side: int = 0
    openings: tuple[Element, ...] = ()
    trims: frozenset[Trim] = frozenset()

    @property
    def length_m(self) -> float:
        return self.plan[self.side % 2]


def default_spec(cfg: Config) -> HouseSpec:
    """Дом без описания — заготовка стаба шага 1 с отделкой по умолчанию."""
    return stub.spec_model("", cfg.models.spec)


def with_materials(spec: HouseSpec, *changes: Material) -> HouseSpec:
    """Дом с заменой материалов палитры по id."""
    by_id = {m.id: m for m in changes}
    return spec.model_copy(update={"materials": [by_id.get(m.id, m) for m in spec.materials]})


def role_material(spec: HouseSpec, role: PaletteRole, **update) -> Material:
    """Материал роли палитры с правкой вида или цвета."""
    return next(m for m in spec.materials if m.id == role).model_copy(update=update)


def window(cfg: Config, view: View, at: float = 0.5,
           variant: OpeningVariant | None = None) -> Element:
    """Окно образца на стороне view; at — где по длине стены: 0 — у левого края, 1 — у правого."""
    sizes = cfg.viewer.catalog.sample.window_m
    w, h = sizes.get(variant.kind if variant else "", sizes["default"])
    return _opening(view, ElementClass.WINDOW, (w, h, cfg.viewer.catalog.sample.sill_m), at,
                    variant)


def door(cfg: Config, view: View, at: float = 0.5,
         variant: OpeningVariant | None = None) -> Element:
    """Входная дверь образца: стоит на цоколе, как у стаба шага 4."""
    w, h = cfg.viewer.catalog.sample.door_m
    return _opening(view, ElementClass.DOOR, (w, h, view.spec.plinth_m), at, variant)


def _opening(view: View, cls: ElementClass, box: tuple[float, float, float], at: float,
             variant: OpeningVariant | None) -> Element:
    w, h, y = box
    return Element(id=f"{cls}1", cls=cls, x_m=round((view.length_m - w) * at, 3), y_m=y, w_m=w,
                   h_m=h, floor=FLOOR, variant=variant)


def render(cfg: Config, view: View) -> str:
    """SVG выбранной стороны образца вместе с кровлей."""
    return svg.facade_roof_svg(_sheet(cfg, view), cfg, view.side)


def _sheet(cfg: Config, view: View) -> FacadeSheet:
    spec = view.spec
    lengths = [view.plan[i % 2] for i in range(len(ORIENTATIONS))]
    facades = [SideFacade(side=Side(index=i, length_m=length, orientation=ORIENTATIONS[i]),
                          zones=_zones(spec, length)) for i, length in enumerate(lengths)]
    facades[view.side] = facades[view.side].model_copy(update={"elements": _elements(cfg, view)})
    return unfold.unfold(FacadeSheet(spec=spec, facades=facades))


def _zones(spec: HouseSpec, length_m: float) -> list[MaterialZone]:
    """Цоколь и основная отделка по всей стене — как у стаба шага 4."""
    return [MaterialZone.rect(ZoneRole.PLINTH, PaletteRole.PLINTH, (0, 0, length_m, spec.plinth_m)),
            MaterialZone.rect(ZoneRole.MAIN, PaletteRole.MAIN,
                              (0, spec.plinth_m, length_m, spec.eaves_m))]


def _elements(cfg: Config, view: View) -> list[Element]:
    """Проёмы образца и выведенные кодом элементы по виду дома (derive.py, шаг 5)."""
    marks = {o.id: {t for t in view.trims if derive.OWNER[t] is o.cls} for o in view.openings}
    wall = derive.Wall(view.spec, view.length_m, cfg.derive)
    return derive.place(list(view.openings), marks, wall)
