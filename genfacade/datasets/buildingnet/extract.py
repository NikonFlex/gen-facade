"""Дом BuildingNet → пример: план и фасады всех сторон (`data: Извлечение BuildingNet`).

Порядок: повернуть модель по осям стен; масштаб — по высоте дверей (`door_quantile`); стены
главного дома — с верхом не ниже `min_wall_m` и под кровлей (без заборов и оград двора). Контур —
прямоугольник: у каждой стороны — самая наружная линия внешнего профиля стен, закрывающая
`min_coverage` её охвата; такой нет — дом не прямоугольник и отбрасывается с причиной. Карниз —
второй снизу из верхов стен четырёх сторон: у двускатной крыши два из них — конёк. Элемент фасада —
компонент с меткой из `[buildingnet.classes]`, плоский вдоль стороны и не глубже `facing_m` от
её плоскости. Выбор и отброшенное — `docs/decisions.md`, 18.10.2026.

Оси: в OBJ Y — вверх; план (x, y) = (X, −Z), высота — от низа стен.
"""

import math
from enum import StrEnum
from statistics import median

import numpy

from genfacade.config import BuildingNet
from genfacade.datasets import rect_house
from genfacade.datasets.buildingnet.mesh import Component, Label
from genfacade.datasets.rect_house import NORMALS, Wall
from genfacade.schema import (
    BuildingType,
    Element,
    ElementClass,
    HouseSpec,
    Material,
    PaletteRole,
    Roof,
    RoofKind,
    Sample,
    Source,
    Split,
)

# Проём, почти целиком лежащий в проёме старшего класса, — его часть: стекло двери, размеченное
# окном, или калитка в воротах гаража.
RANK = {ElementClass.GARAGE_DOOR: 0, ElementClass.DOOR: 1, ElementClass.WINDOW: 2}
DIAGONAL = math.cos(math.pi / 4)  # грань смотрит на сторону, если отклонена меньше чем на 45°


class Reason(StrEnum):
    """Почему дом не извлечён: счётчики причин — в описи источника."""

    NO_DOOR = "no_door"            # нет дверей — не по чему взять масштаб
    NO_WALLS = "no_walls"          # нет стен выше min_wall_m
    NOT_RECTANGLE = "not_rectangle"
    LOW = "low"                    # карниз ниже цоколя и одного этажа


class Rejected(Exception):
    def __init__(self, reason: Reason, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason


def house(model: str, parts: list[Component], cfg: BuildingNet) -> Sample:
    parts = _upright(_turned(parts), cfg)
    lo, hi = _footprint(parts, cfg)
    fp = rect_house.rectangle(lo, hi, cfg.wall_m)
    # Второй снизу верх стен: у двускатной крыши два верха — карниз, два — конёк, а одна
    # низкая стена (пристройка, веранда) не опускает карниз всего дома.
    eaves = sorted(_wall_top(w, parts, cfg) for w in fp.walls)[1]
    plinth = _plinth(parts, cfg)
    spec = _spec(plinth, eaves, cfg)
    facades = [_facade(w, parts, spec, cfg) for w in fp.walls]
    first = max(range(4), key=lambda i: (_doors(facades[i]), fp.walls[i].length))
    laid = [((first + k) % 4, facades[(first + k) % 4]) for k in range(4)]
    plan, sheet = rect_house.assemble(spec, fp, laid, Source.BUILDINGNET)
    return Sample(id=model, source=Source.BUILDINGNET, split=Split.TEST, plan=plan, sheet=sheet)


def _turned(parts: list[Component]) -> list[Component]:
    """Повернуть вокруг Y так, чтобы стены легли по осям: угол — взвешенное по площади среднее
    направлений нормалей стен по модулю 90° (через 4θ, иначе 0° и 90° гасят друг друга)."""
    tri = [(c.vertices[c.faces], c) for c in parts if c.label is Label.WALL]
    if not tri:
        return parts
    normals = numpy.concatenate([numpy.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
                                 for t, _ in tri])
    theta = numpy.arctan2(normals[:, 2], normals[:, 0])
    weight = numpy.hypot(normals[:, 0], normals[:, 2])  # вертикальная часть площади грани
    angle = math.atan2((weight * numpy.sin(4 * theta)).sum(),
                       (weight * numpy.cos(4 * theta)).sum()) / 4
    c, s = math.cos(angle), math.sin(angle)
    turn = numpy.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return [p._replace(vertices=p.vertices @ turn.T) for p in parts]


def _upright(parts: list[Component], cfg: BuildingNet) -> list[Component]:
    """Метры по дверям, план (x, y) = (X, −Z), высота — от низа стен."""
    doors = [numpy.ptp(c.vertices[:, 1]) for c in parts if c.label is Label.DOOR]
    if not doors:
        raise Rejected(Reason.NO_DOOR, "в модели нет дверей")
    # Дверь в разметке бывает разбита на полотно и филёнки: медиана компонентов меньше двери.
    k = cfg.door_height_m / float(numpy.quantile(doors, cfg.door_quantile))
    out = [p._replace(vertices=numpy.c_[p.vertices[:, 0], -p.vertices[:, 2], p.vertices[:, 1]] * k)
           for p in parts]
    walls = [c for c in out if c.label is Label.WALL]
    if not walls:
        raise Rejected(Reason.NO_WALLS, "в модели нет стен")
    ground = min(c.vertices[:, 2].min() for c in walls)
    return [p._replace(vertices=p.vertices - (0.0, 0.0, ground)) for p in out]


def _main_walls(parts: list[Component], cfg: BuildingNet) -> list[Component]:
    """Стены дома, а не заборы и ограды двора: верх не ниже min_wall_m и середина — под крышей
    (в охвате кровли с запасом facing_m). По высоте самого компонента не отбирать — стену дома
    BuildingNet часто режет на полосы между окнами."""
    roof = _roof_box(parts, cfg)
    tall = [c for c in parts if c.label is Label.WALL and c.vertices[:, 2].max() >= cfg.min_wall_m
            and _inside(c.vertices[:, :2].mean(axis=0), roof)]
    if not tall:
        raise Rejected(Reason.NO_WALLS, f"нет стен с верхом выше {cfg.min_wall_m} м")
    return tall


def _roof_box(parts: list[Component], cfg: BuildingNet) -> tuple:
    """Охват кровли в плане с запасом facing_m; кровли нет — вся плоскость."""
    roofs = [c.vertices[:, :2] for c in parts if c.label is Label.ROOF]
    if not roofs:
        return -numpy.inf, numpy.inf
    xy = numpy.concatenate(roofs)
    return xy.min(axis=0) - cfg.facing_m, xy.max(axis=0) + cfg.facing_m


def _inside(point: numpy.ndarray, box: tuple) -> bool:
    return bool(numpy.all((box[0] <= point) & (point <= box[1])))


def _wall_tris(parts: list[Component], cfg: BuildingNet) -> numpy.ndarray:
    """Треугольники главных стен: m × 3 вершины × (x, y, высота)."""
    return numpy.concatenate([c.vertices[c.faces] for c in _main_walls(parts, cfg)])


def _footprint(parts: list[Component], cfg: BuildingNet) -> tuple[numpy.ndarray, numpy.ndarray]:
    """Прямоугольник главного дома: у каждой стороны — самая наружная линия стен, которая
    закрывает min_coverage охвата стен вдоль стороны; выступ (крыльцо, эркер) её не сдвигает."""
    tris = _wall_tris(parts, cfg)
    hi = [_plane(tris, numpy.array(n), cfg) for n in NORMALS]
    # NORMALS: +y, +x, −y, −x → верх, право, низ (со знаком минус), лево (со знаком минус)
    lo, hi = numpy.array([-hi[3], -hi[2]]), numpy.array([hi[1], hi[0]])
    if (hi - lo).min() < cfg.min_side_m:
        raise Rejected(Reason.NOT_RECTANGLE, f"сторона прямоугольника {(hi - lo).min():.2f} м")
    return lo, hi


def _toward(tris: numpy.ndarray, normal: numpy.ndarray) -> numpy.ndarray:
    """Треугольники, смотрящие на сторону. Обход граней в OBJ не согласован: нормаль бывает и
    внутрь — берётся по модулю."""
    n = numpy.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])[:, :2]
    size = numpy.maximum(numpy.linalg.norm(n, axis=1), 1e-12)
    return tris[numpy.abs(n @ normal) > DIAGONAL * size]


def _plane(tris: numpy.ndarray, normal: numpy.ndarray, cfg: BuildingNet) -> float:
    """Самая наружная глубина p, у которой внешний профиль стен лежит в [p − facing_m, p] на
    min_coverage охвата. Профиль — самая наружная стена в каждой точке вдоль стороны:
    перегородки внутри дома размечены той же меткой «wall» и не должны засчитываться."""
    face = _toward(tris, normal)
    profile = _profile(face, normal, cfg.profile_step_m) if len(face) else numpy.empty(0)
    for p in sorted(set(profile[numpy.isfinite(profile)].tolist()), reverse=True):
        if ((profile >= p - cfg.facing_m) & (profile <= p)).mean() >= cfg.min_coverage:
            return p
    raise Rejected(Reason.NOT_RECTANGLE,
                   f"у стороны с нормалью {tuple(normal)} нет линии стен на "
                   f"{cfg.min_coverage:.0%} длины")


def _profile(face: numpy.ndarray, normal: numpy.ndarray, step: float) -> numpy.ndarray:
    """Глубина самой наружной стены в каждом отрезке step вдоль стороны; −inf — стены нет."""
    right = numpy.array((-normal[1], normal[0]))
    depth = (face[:, :, :2] @ normal).max(axis=1)
    across = face[:, :, :2] @ right
    first = across.min()
    lo = ((across.min(axis=1) - first) / step).astype(int)
    hi = numpy.maximum(((across.max(axis=1) - first) / step).astype(int), lo + 1)
    out = numpy.full(hi.max(), -numpy.inf)
    for a, b, d in zip(lo, hi, depth, strict=True):
        out[a:b] = numpy.maximum(out[a:b], d)
    return out


def _facing(w: Wall, parts: list[Component], cfg: BuildingNet) -> numpy.ndarray:
    """Треугольники главных стен, смотрящие на сторону и лежащие у её плоскости."""
    face = _toward(_wall_tris(parts, cfg), w.normal)
    depth = (face[:, :, :2] @ w.normal).max(axis=1)
    return face[abs(depth - w.plane) <= cfg.facing_m]


def _wall_top(w: Wall, parts: list[Component], cfg: BuildingNet) -> float:
    """Верх стены стороны: у фронтона он — конёк, поэтому карниз — нижний из четырёх."""
    return float(_facing(w, parts, cfg)[:, :, 2].max())


def _covered(spans: list[tuple[float, float]]) -> float:
    """Длина объединения отрезков, отсортированных по началу."""
    total, end = 0.0, -math.inf
    for a, b in spans:
        if b > end:
            total += b - max(a, end)
            end = b
    return total


def _plinth(parts: list[Component], cfg: BuildingNet) -> float:
    """Цоколь — медиана низа дверей первого этажа: пол первого этажа на этой высоте."""
    bottoms = [float(c.vertices[:, 2].min()) for c in parts if c.label is Label.DOOR]
    low = [b for b in bottoms if b <= cfg.max_plinth_m]
    return max(0.0, median(low)) if low else 0.0


def _spec(plinth: float, eaves: float, cfg: BuildingNet) -> HouseSpec:
    if eaves - plinth < cfg.floor_height_m / 2:
        raise Rejected(Reason.LOW, f"карниз {eaves:.2f} м при цоколе {plinth:.2f} м")
    floors = max(1, round((eaves - plinth) / cfg.floor_height_m))
    return HouseSpec(building_type=BuildingType.COTTAGE, floors=floors,
                     floor_heights_m=[(eaves - plinth) / floors] * floors, plinth_m=plinth,
                     eaves_m=eaves, roof=Roof(kind=RoofKind.FLAT),
                     materials=[Material(id=PaletteRole.MAIN, kind=cfg.material)])


def _facade(w: Wall, parts: list[Component], spec: HouseSpec, cfg: BuildingNet) -> list[Element]:
    boxes = [(cfg.classes[c.label], box) for c in parts if c.label in cfg.classes
             if (box := _on_wall(w, c, spec, cfg)) is not None]
    merged = _absorbed(_merged(boxes))
    return [Element(id=f"e{k}", cls=cls, x_m=x0, y_m=y0, w_m=x1 - x0, h_m=y1 - y0,
                    floor=rect_house.floor_of((y0 + y1) / 2, spec))
            for k, (cls, (x0, y0, x1, y1)) in enumerate(merged)]


def _on_wall(w: Wall, c: Component, spec: HouseSpec, cfg: BuildingNet) -> tuple | None:
    """Прямоугольник компонента на фасаде стороны, обрезанный по стене; None — не на ней."""
    depth, across = c.vertices[:, :2] @ w.normal, c.vertices[:, :2] @ w.right - w.left
    if depth.max() < w.plane - cfg.facing_m or numpy.ptp(depth) >= numpy.ptp(across):
        return None
    x0, x1 = float(across.min()), float(across.max())
    y0, y1 = float(c.vertices[:, 2].min()), float(c.vertices[:, 2].max())
    cx0, cx1, cy0, cy1 = max(x0, 0.0), min(x1, w.length), max(y0, 0.0), min(y1, spec.eaves_m)
    if cx1 - cx0 < cfg.min_element_m or cy1 - cy0 < cfg.min_element_m:
        return None
    inside = (cx1 - cx0) * (cy1 - cy0) / ((x1 - x0) * (y1 - y0))
    return (cx0, cy0, cx1, cy1) if inside >= cfg.inside_share else None


def _overlap(a: tuple, b: tuple) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _merged(boxes: list[tuple]) -> list[tuple]:
    """Пересекающиеся прямоугольники одного класса — один элемент: окно в BuildingNet часто
    размечено рамой и стёклами отдельными компонентами."""
    out: list[tuple] = []
    for cls, box in boxes:
        while (hit := next((o for o in out if o[0] is cls and _overlap(o[1], box) > 0), None)):
            out.remove(hit)
            box = (min(box[0], hit[1][0]), min(box[1], hit[1][1]),
                   max(box[2], hit[1][2]), max(box[3], hit[1][3]))
        out.append((cls, box))
    return out


def _absorbed(boxes: list[tuple]) -> list[tuple]:
    """Убрать проём, почти целиком лежащий в проёме старшего класса (RANK)."""
    def inner(cls: ElementClass, box: tuple) -> bool:
        area = (box[2] - box[0]) * (box[3] - box[1])
        return cls in RANK and any(o in RANK and RANK[o] < RANK[cls] and
                                   _overlap(b, box) >= area / 2 for o, b in boxes)
    return [(cls, box) for cls, box in boxes if not inner(cls, box)]


def _doors(elements: list[Element]) -> int:
    return sum(e.cls is ElementClass.DOOR and e.floor == 1 for e in elements)
