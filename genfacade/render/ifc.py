"""Дом в BIM: лист фасадов → файл IFC4 с объектами, а не мешем (gf#392).

Этажи — IfcBuildingStorey, стены по сторонам листа — IfcWall (силуэт стены с фронтоном — профиль
выдавливания, толщина `ifc.wall_thickness_m` внутрь от контура плана), проёмы — IfcOpeningElement
в стене с IfcWindow и IfcDoor на своих местах и размерах, перекрытия — IfcSlab, крыша — IfcRoof из
плит скатов (roof.py) или плоской плиты. Материал стены — IfcMaterial с видом отделки, цвет — из
палитры дома. Метры плана, как у дома объёмом (render/house3d.py). Из того, что ставит модель на
шаге 4, идут ещё ставни (IfcShadingDevice SHUTTER — створка на элемент листа, пара у окна),
козырьки над дверью (IfcSlab ROOF формой из вида дома) и крыльцо (IfcSlab BASESLAB профилем
ступеней, как в 3D). Цоколь, карниз, наличники, подоконник и деление рамы в IFC не идут: здесь
объёмы здания, а не отделка (решение хозяина 10.11).
"""

import math
from collections import defaultdict
from typing import NamedTuple

import shapely
import shapely.affinity

from genfacade import dormers, parts, porch_roofs, roof, roof_items, skylights, unfold
from genfacade.config import Config, PorchRoofLook
from genfacade.render.house3d import house_3d
from genfacade.render.ifc_step import STAR, Enum, Ref, Step, Typed, guid
from genfacade.render.svg import Pen, element_fill, pen_for
from genfacade.schema import (
    EPS,
    OPENINGS,
    CanopyShape,
    Element,
    ElementClass,
    FacadeSheet,
    PaletteRole,
    Point,
    RoofKind,
    SideFacade,
)

Vec = tuple[float, ...]
SCHEMA = "IFC4"
IFC_FILE = "house.ifc"  # имя файла выгрузки: в папке прогона и в шапке IFC
AUTHOR = "genfacade"
UP, DOWN = (0.0, 0.0, 1.0), (0.0, 0.0, -1.0)
ARCH_STEPS = 16  # звеньев свода арочного козырька (как в 3D, house3d_relief.js)
RGB_MAX = 255
HEX_LEN = 7  # "#rrggbb"
DOOR_TYPE = {ElementClass.DOOR: "DOOR", ElementClass.GARAGE_DOOR: "GATE"}
COMMON = {ElementClass.WINDOW: "Pset_WindowCommon", ElementClass.DOOR: "Pset_DoorCommon",
          ElementClass.GARAGE_DOOR: "Pset_DoorCommon"}


def house_ifc(sheet: FacadeSheet, cfg: Config, name: str = IFC_FILE) -> str:
    """Текст файла IFC4 дома по листу."""
    return IfcHouse(sheet, cfg, name).build()


def counts(text: str) -> dict[str, int]:
    """Сколько сущностей каждого вида в тексте IFC: `{"IFCWALL": 4, …}` — для проверки выгрузки."""
    found: dict[str, int] = defaultdict(int)
    for line in text.splitlines():
        if line.startswith("#") and "=" in line and "(" in line:
            found[line.split("=", 1)[1].split("(", 1)[0]] += 1
    return dict(found)


def _sub(a: Vec, b: Vec) -> Vec:
    return tuple(x - y for x, y in zip(a, b, strict=True))


def _length(a: Vec) -> float:
    return math.sqrt(_dot(a, a))


def _perp(a: Vec, z: Vec) -> Vec:
    """Часть вектора a, перпендикулярная единичному z."""
    k = _dot(a, z)
    return tuple(x - k * c for x, c in zip(a, z, strict=True))


def _up(n: Vec) -> Vec:
    return n if n[2] >= 0 else tuple(-c for c in n)


def _frame(points: list[Vec], normal: Vec) -> tuple[Vec, Vec, Vec, Vec]:
    """Местные оси плоского многоугольника: начало, x, y и z — единичная нормаль."""
    p0, z = points[0], _unit(normal)
    x = _unit(next(d for q in points[1:] if _length(d := _perp(_sub(q, p0), z)) > EPS))
    return p0, x, _cross(z, x), z


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Vec, b: Vec) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _unit(a: Vec) -> Vec:
    n = math.sqrt(_dot(a, a))
    return tuple(x / n for x in a)


def _normal(points: list[Vec]) -> Vec:
    """Нормаль многоугольника в объёме по Ньюэллу; знак — по обходу."""
    n = [0.0, 0.0, 0.0]
    for p, q in zip(points, points[1:] + points[:1], strict=True):
        n[0] += (p[1] - q[1]) * (p[2] + q[2])
        n[1] += (p[2] - q[2]) * (p[0] + q[0])
        n[2] += (p[0] - q[0]) * (p[1] + q[1])
    return _unit(tuple(n))


def _rgb(color: str) -> tuple[float, float, float]:
    return tuple(int(color[i:i + 2], 16) / RGB_MAX for i in (1, 3, 5))  # type: ignore[return-value]


class Writer:
    """Примитивы IFC поверх Step: точки, оси, размещения, выдавливания, стили, связи."""

    def __init__(self, name: str, tolerance: float):
        self.s = Step(SCHEMA, name, AUTHOR)
        self.name = name
        self.styles: dict[str, Ref] = {}
        origin = self.axis((0.0, 0.0, 0.0))
        self.context = self.s.add("IfcGeometricRepresentationContext", None, "Model", 3,
                                  tolerance, origin, None)
        self.body = self.s.add("IfcGeometricRepresentationSubContext", "Body", "Model", STAR,
                               STAR, STAR, STAR, self.context, None, Enum("MODEL_VIEW"), None)

    def units(self) -> Ref:
        si = [self.s.add("IfcSIUnit", STAR, Enum(kind), None, Enum(unit)) for kind, unit in (
            ("LENGTHUNIT", "METRE"), ("AREAUNIT", "SQUARE_METRE"),
            ("VOLUMEUNIT", "CUBIC_METRE"), ("PLANEANGLEUNIT", "RADIAN"))]
        return self.s.add("IfcUnitAssignment", si)

    def point(self, p: Vec) -> Ref:
        return self.s.add("IfcCartesianPoint", [float(c) for c in p])

    def direction(self, d: Vec) -> Ref:
        return self.s.add("IfcDirection", [float(c) for c in d])

    def axis(self, origin: Vec, z: Vec | None = None, x: Vec | None = None) -> Ref:
        return self.s.add("IfcAxis2Placement3D", self.point(origin),
                          self.direction(z) if z else None, self.direction(x) if x else None)

    def place(self, rel: Ref | None, origin: Vec, z: Vec | None = None, x: Vec | None = None
              ) -> Ref:
        return self.s.add("IfcLocalPlacement", rel, self.axis(origin, z, x))

    def polygon(self, ring: list[Point]) -> Ref:
        pts = [self.s.add("IfcCartesianPoint", [float(x), float(y)]) for x, y in ring]
        line = self.s.add("IfcPolyline", [*pts, pts[0]])
        return self.s.add("IfcArbitraryClosedProfileDef", Enum("AREA"), None, line)

    def circle(self, radius: float) -> Ref:
        centre = self.s.add("IfcAxis2Placement2D",
                            self.s.add("IfcCartesianPoint", [0.0, 0.0]), None)
        return self.s.add("IfcCircleProfileDef", Enum("AREA"), None, centre, radius)

    def rect(self, w: float, h: float) -> Ref:
        centre = self.s.add("IfcAxis2Placement2D", self.s.add(
            "IfcCartesianPoint", [w / 2, h / 2]), None)
        return self.s.add("IfcRectangleProfileDef", Enum("AREA"), None, centre, w, h)

    def solid(self, profile: Ref, depth: float, color: str | None = None,
              transparency: float = 0.0) -> Ref:
        """Выдавливание профиля на depth вдоль −z местных осей; color — цвет, нет — без стиля."""
        return self.solid_along(profile, DOWN, depth, color, transparency)

    def solid_along(self, profile: Ref, direction: Vec, depth: float, color: str | None,
                    transparency: float = 0.0) -> Ref:
        """Выдавливание профиля на depth вдоль direction (в местных осях профиля)."""
        item = self.s.add("IfcExtrudedAreaSolid", profile, self.axis((0.0, 0.0, 0.0)),
                          self.direction(direction), depth)
        if color is not None:
            self.s.add("IfcStyledItem", item, [self.style(color, transparency)], None)
        return item

    def style(self, color: str, transparency: float) -> Ref:
        key = f"{color}/{transparency}"
        if key not in self.styles:
            r, g, b = _rgb(color)
            rgb = self.s.add("IfcColourRgb", None, r, g, b)
            render = self.s.add("IfcSurfaceStyleRendering", rgb, transparency, None, None, None,
                                None, None, None, Enum("NOTDEFINED"))
            self.styles[key] = self.s.add("IfcSurfaceStyle", color, Enum("BOTH"), [render])
        return self.styles[key]

    def shape(self, items: list[Ref]) -> Ref:
        rep = self.s.add("IfcShapeRepresentation", self.body, "Body", "SweptSolid", items)
        return self.s.add("IfcProductDefinitionShape", None, None, [rep])

    def product(self, kind: str, key: str, name: str, place: Ref | None, shape: Ref | None,
                *tail: object) -> Ref:
        return self.s.add(kind, guid(f"{self.name}/{key}"), None, name, None, None, place, shape,
                          *tail)

    def relate(self, kind: str, key: str, *attrs: object) -> Ref:
        return self.s.add(kind, guid(f"{self.name}/{kind}/{key}"), None, None, None, *attrs)

    def props(self, key: str, owner: Ref, name: str, values: dict[str, object]) -> None:
        single = [self.s.add("IfcPropertySingleValue", n, None, v, None)
                  for n, v in values.items()]
        pset = self.s.add("IfcPropertySet", guid(f"{self.name}/pset/{key}/{name}"), None, name,
                          None, single)
        self.relate("IfcRelDefinesByProperties", f"{key}/{name}", [owner], pset)


class Bar(NamedTuple):
    """Горизонтальная труба или желоб в IFC: вид, концы оси в плане, высота оси, сечение (сторона
    квадрата или диаметр круга) и круглое ли оно."""

    kind: str
    ends: tuple[Point, Point]
    z: float
    size: float
    round: bool


def label(text: str) -> Typed:
    return Typed("IfcLabel", text)


def real(x: float) -> Typed:
    return Typed("IfcReal", float(x))


def boolean(x: bool) -> Typed:
    return Typed("IfcBoolean", x)


def integer(x: int) -> Typed:
    return Typed("IfcInteger", x)


class IfcHouse:
    """Сборка IFC дома: пространственная структура, стены с проёмами, перекрытия, крыша."""

    def __init__(self, sheet: FacadeSheet, cfg: Config, name: str):
        self.sheet, self.cfg, self.ifc = sheet, cfg, cfg.ifc
        self.pen: Pen = pen_for(sheet, cfg)
        self.w = Writer(name, cfg.ifc.tolerance)
        self.data = house_3d(sheet, cfg)
        house = roof.roofs(sheet)
        self.dormers = dormers.build(sheet, cfg)  # слуховые окна (gf#457)
        self.faces = dormers.cut(roof.house_faces(house), self.dormers) if house else []
        self.levels = sheet.spec.floor_levels()
        self.roof_m = cfg.sheet.roof.thickness_m  # одна толщина кровли с листом и 3D (gf#447)
        self.storeys: list[Ref] = []
        self.contained: dict[int, list[Ref]] = defaultdict(list)  # этаж → объекты
        self.walls: list[Ref] = []
        self.roof_slabs: list[Ref] = []
        self.awnings: list[Ref] = []  # кровли навесов на столбах: материал — кровли дома

    def build(self) -> str:
        self._structure()
        for k, f in enumerate(self.sheet.facades):
            self._wall(k, f)
        self._joints()
        self._dormers()
        self._slabs()
        self._roof()
        self._roof_items()
        self._porch_roofs()
        self._skylights()
        self._finish()
        return self.w.s.render()

    # ——— пространственная структура ———

    def _structure(self) -> None:
        w, n = self.w, self.ifc.names
        self.project = w.s.add("IfcProject", guid(f"{w.name}/project"), None, n.project, None,
                               None, None, None, [w.context], w.units())
        site_place = w.place(None, (0.0, 0.0, 0.0))
        self.building_place = w.place(site_place, (0.0, 0.0, 0.0))
        site = w.product("IfcSite", "site", n.site, site_place, None, None, Enum("ELEMENT"),
                         None, None, None, None, None)
        self.building = w.product("IfcBuilding", "building", n.building, self.building_place,
                                  None, None, Enum("ELEMENT"), None, None, None)
        w.relate("IfcRelAggregates", "project", self.project, [site])
        w.relate("IfcRelAggregates", "site", site, [self.building])
        for k in range(self.sheet.spec.floors):
            place = w.place(self.building_place, (0.0, 0.0, self.levels[k]))
            self.storeys.append(w.product(
                "IfcBuildingStorey", f"storey{k}", n.storey.format(n=k + 1), place, None, None,
                Enum("ELEMENT"), self.levels[k]))
        w.relate("IfcRelAggregates", "building", self.building, self.storeys)

    def _storey_at(self, z: float) -> int:
        """Этаж, на отметке которого лежит z: последний, чей низ не выше z."""
        return max((k for k in range(len(self.storeys)) if self.levels[k] <= z + EPS), default=0)

    # ——— стены ———

    def _wall_shape(self, k: int, f: SideFacade) -> shapely.Geometry:
        """Силуэт стены вместе с фронтоном над карнизом (roof.house_above) — один профиль."""
        sil = f.silhouette or unfold.silhouette(f.side.length_m, self.sheet.spec.eaves_m, f.runs)
        body = shapely.Polygon(sil)
        house = roof.roofs(self.sheet)
        if house is None:
            return body
        above = [shapely.Polygon(p).buffer(0) for p in roof.house_above(house, k)]
        # стена не выше кровли и на внутренней грани: под односкатной скат там ниже
        inner = [shapely.Polygon(p).buffer(0) for p in roof.house_above(
            house, k, self.ifc.wall_thickness_m)]
        top = shapely.union_all([body, *above]).intersection(shapely.union_all([body, *inner]))
        # грань ската — низ плиты кровли: верх стены уходит в её толщу, до верха плиты минус посадка
        # (вровень с верхом он мерцает поверх кровли)
        return top.union(shapely.affinity.translate(
            top, yoff=self.roof_m - self.ifc.roof_seat_m))

    def _trim(self, k: int, shape: shapely.Geometry) -> list[list[Point]]:
        """Профили стены k с торцом у левого угла, сдвинутым на толщину: на выпуклом углу стена
        короче — угол занимает соседняя, на вогнутом длиннее — иначе в углу дыра в толщину."""
        if self.data["walls"][k]["convex_left"]:  # срез по x ≥ t, а не сдвиг вершин: верх
            x0, y0, x1, y1 = shape.bounds  # фронтона и скат не уезжают с высоты
            shape = shape.intersection(shapely.box(self.ifc.wall_thickness_m, y0 - 1, x1 + 1,
                                                   y1 + 1))
        else:
            shape = self._inner_corner(k, shape)
        return roof.polygons(shape)

    def _inner_corner(self, k: int, shape: shapely.Geometry) -> shapely.Geometry:
        """Стена k на вогнутом левом углу, продолженная за угол на толщину t. Квадрат угла — не выше
        кровли над ним с посадкой: у дома из крыльев кровля над углом бывает ниже торца стены
        (односкатные крылья одной высоты, gf#431)."""
        t = self.ifc.wall_thickness_m
        moved = shapely.union_all([
            shapely.Polygon([(x - t if abs(x) < EPS else x, y) for x, y in ring])
            for ring in roof.polygons(shape)])
        (lx, ly), u = self._axis(k)
        tops = [self.roof_top((lx + u[0] * x - u[1] * d, ly + u[1] * x + u[0] * d))
                for x in (-t, 0.0) for d in (0.0, t)]
        if any(top is None for top in tops):
            return moved
        cap = min(tops) - self.ifc.roof_seat_m
        return moved.intersection(shapely.box(-t, -1.0, 0.0, cap).union(
            shapely.box(0.0, -1.0, roof.FAR, roof.FAR)))

    def roof_top(self, p: Point) -> float | None:
        """Верх плиты кровли над точкой плана — самая высокая из граней (низов плит) над ней плюс
        толщина кровли; кровли нет — None."""
        tops = []
        for face in self.faces:
            if shapely.Polygon([q[:2] for q in face]).buffer(EPS).contains(shapely.Point(p)):
                n = _normal(face)
                tops.append(face[0][2] - ((p[0] - face[0][0]) * n[0]
                                          + (p[1] - face[0][1]) * n[1]) / n[2])
        return max(tops) + self.roof_m if tops else None

    def _axis(self, k: int) -> tuple[Point, Vec]:
        """Левый край стены k снаружи и единичное направление вдоль неё."""
        wall = self.data["walls"][k]
        (lx, ly), (rx, ry) = wall["left"], wall["right"]
        return (lx, ly), _unit((rx - lx, ry - ly, 0.0))

    def _wall(self, k: int, f: SideFacade) -> None:
        w, t = self.w, self.ifc.wall_thickness_m
        (lx, ly), u = self._axis(k)
        out = (u[1], -u[0], 0.0)
        place = w.place(self.building_place, (lx, ly, 0.0), out, u)
        color = self.pen.colors.get(PaletteRole.MAIN, self.cfg.library.fill.wall)
        items = [w.solid(w.polygon(ring), t, color)
                 for ring in self._trim(k, self._wall_shape(k, f))]
        name = self.ifc.names.wall.format(side=f.side.index)
        ref = w.product("IfcWall", f"wall{k}", name, place, w.shape(items), None,
                        Enum("STANDARD"))
        w.props(f"wall{k}", ref, "Pset_WallCommon", {"IsExternal": boolean(True)})
        w.props(f"wall{k}", ref, self.ifc.pset.facade, {
            "Side": integer(f.side.index), "Material": label(PaletteRole.MAIN)})
        self.walls.append(ref)
        self.contained[0].append(ref)
        for e in f.elements:
            if e.cls in OPENINGS:
                self._opening(k, ref, place, e)
            elif e.cls is ElementClass.BLIND:
                self._shutter(k, place, e)
        for r in self.data["walls"][k]["relief"]:
            if r["cls"] is ElementClass.CANOPY:
                self._canopy(k, place, r)
            elif r["cls"] is ElementClass.PORCH:
                self._porch(k, place, r)

    def _opening(self, k: int, wall: Ref, place: Ref, e: Element) -> None:
        """Проём в стене и его заполнение — окно или дверь — по рамке элемента листа."""
        w, ifc = self.w, self.ifc
        side = self.sheet.facades[k].side.index
        key, m, t = f"{side}-{e.id}", ifc.opening_margin_m, ifc.wall_thickness_m
        hole = w.solid(w.rect(e.w_m, e.h_m), t + 2 * m)
        opening = w.product("IfcOpeningElement", f"opening/{key}", ifc.names.opening.format(
            id=e.id), w.place(place, (e.x_m, e.y_m, m)), w.shape([hole]), None, Enum("OPENING"))
        w.relate("IfcRelVoidsElement", f"void/{key}", wall, opening)
        window = e.cls is ElementClass.WINDOW
        color = self.cfg.library.fill.glass if window else element_fill(e, self.pen)
        d = ifc.window_depth_m
        body = w.solid(w.rect(e.w_m, e.h_m), d, color, ifc.glass_transparency if window else 0.0)
        filler = self._filler(e, key, w.place(place, (e.x_m, e.y_m, -(t - d) / 2)),
                              w.shape([body]))
        w.relate("IfcRelFillsElement", f"fill/{key}", opening, filler)
        storey = self._storey_at(e.y_m)
        w.props(f"fill/{key}", filler, ifc.pset.facade, {
            "Side": integer(side), "Id": label(e.id), "Class": label(e.cls),
            "Floor": integer(e.floor if e.floor is not None else storey + 1)})
        w.props(f"fill/{key}", filler, COMMON[e.cls], {"IsExternal": boolean(True)})
        self.contained[storey].append(filler)

    def _filler(self, e: Element, key: str, place: Ref, shape: Ref) -> Ref:
        names = self.ifc.names
        if e.cls is ElementClass.WINDOW:
            return self.w.product("IfcWindow", f"window/{key}", names.window.format(id=e.id),
                                  place, shape, None, e.h_m, e.w_m, Enum("WINDOW"),
                                  Enum("NOTDEFINED"), None)
        name = names.garage_door if e.cls is ElementClass.GARAGE_DOOR else names.door
        return self.w.product("IfcDoor", f"door/{key}", name.format(id=e.id), place, shape,
                              None, e.h_m, e.w_m, Enum(DOOR_TYPE[e.cls]), Enum("NOTDEFINED"),
                              None)

    # ——— то, что стоит на стене: ставни, козырёк, крыльцо ———
    # Местные оси стены: x вдоль стены от левого края, y вверх, z наружу. Выдавливание идёт вниз по
    # z местного размещения, поэтому вынос depth — размещение на z=depth и выдавливание на depth.

    def _front(self, place: Ref, ring: list[Point], depth: float, color: str) -> tuple[Ref, Ref]:
        """Профиль в плоскости стены (x, y), вынесенный наружу на depth: размещение и тело."""
        w = self.w
        return w.place(place, (0.0, 0.0, depth)), w.solid(w.polygon(ring), depth, color)

    def _side(self, place: Ref, ring: list[Point], x0: float, x1: float, color: str
              ) -> tuple[Ref, Ref]:
        """Профиль сбоку (z наружу, y вверх), вытянутый вдоль стены от x0 до x1."""
        w = self.w
        at = w.place(place, (x0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        return at, w.solid(w.polygon(ring), x1 - x0, color)

    def _extra(self, kind: str, key: str, name: str, side: int, e_id: str, cls: str,
               y: float, parts_: tuple[Ref, Ref], *tail: object) -> None:
        """Объект выступа: размещение и тело, свойства GenFacade, этаж по низу."""
        w = self.w
        storey = self._storey_at(y)
        ref = w.product(kind, key, name, parts_[0], w.shape([parts_[1]]), None, *tail)
        w.props(key, ref, self.ifc.pset.facade, {
            "Side": integer(side), "Id": label(e_id), "Class": label(cls),
            "Floor": integer(storey + 1)})
        self.contained[storey].append(ref)

    def _shutter(self, k: int, place: Ref, e: Element) -> None:
        side = self.sheet.facades[k].side.index
        ring = [(e.x_m, e.y_m), (e.x_m + e.w_m, e.y_m), (e.x_m + e.w_m, e.y_m + e.h_m),
                (e.x_m, e.y_m + e.h_m)]
        self._extra("IfcShadingDevice", f"shutter/{side}-{e.id}",
                    self.ifc.names.shutter.format(id=e.id), side, e.id, e.cls, e.y_m,
                    self._front(place, ring, self.ifc.shutter_m, element_fill(e, self.pen)),
                    Enum("SHUTTER"))

    def _canopy(self, k: int, place: Ref, r: dict) -> None:
        """Козырёк формой, как в 3D (house3d_relief.js): двускатный — треугольник, арка — свод,
        плита с уклоном — клин; на кронштейнах и столбах — плита сверху (кронштейны и столбы
        в IFC не идут)."""
        look, d = self.cfg.viewer.house3d, r["depth"]
        x0, x1, y0, y1 = r["x0"], r["x1"], r["y0"], r["y1"]
        side = self.sheet.facades[k].side.index
        if r["shape"] == CanopyShape.GABLE:
            parts_ = self._front(place, [(x0, y0), (x1, y0), ((x0 + x1) / 2, y1)], d, r["color"])
        elif r["shape"] == CanopyShape.ARCHED:
            mid, half, rise = (x0 + x1) / 2, (x1 - x0) / 2, y1 - y0
            dome = [(mid + half * math.cos(math.pi * (1 - i / ARCH_STEPS)),
                     y0 + rise * math.sin(math.pi * (1 - i / ARCH_STEPS)))
                    for i in range(ARCH_STEPS + 1)]
            parts_ = self._front(place, [(x0, y0), (x1, y0), *reversed(dome)], d, r["color"])
        elif r["shape"] == CanopyShape.SLAB:
            h = y1 - y0
            ring = [(0.0, y0), (d, y0), (d, y0 + h * look.slope_edge), (0.0, y1)]
            parts_ = self._side(place, ring, x0, x1, r["color"])
        else:
            top = y1 - min(self.cfg.sheet.trim.slab_m, y1 - y0)
            parts_ = self._front(place, [(x0, top), (x1, top), (x1, y1), (x0, y1)], d, r["color"])
        e = r["id"]
        self._extra("IfcSlab", f"canopy/{side}-{e}", self.ifc.names.canopy.format(id=e), side, e,
                    ElementClass.CANOPY, y0, parts_, Enum("ROOF"))

    def _porch(self, k: int, place: Ref, r: dict) -> None:
        """Крыльцо: площадка глубиной depth и ступени перед ней — профиль лестницы вдоль стены,
        как в 3D; одна плита (IfcSlab BASESLAB)."""
        look, n, d = self.cfg.viewer.house3d, r["steps"], r["depth"]
        rise = (r["y1"] - r["y0"]) / n

        def out(i: int) -> float:
            return d + (n - i) * look.tread_m

        ring: list[Point] = [(0.0, r["y0"]), (out(1), r["y0"])]
        for i in range(1, n + 1):
            ring.append((out(i), r["y0"] + i * rise))
            if i < n:
                ring.append((out(i + 1), r["y0"] + i * rise))
        ring.append((0.0, r["y1"]))
        side = self.sheet.facades[k].side.index
        e = r["id"]
        self._extra("IfcSlab", f"porch/{side}-{e}", self.ifc.names.porch.format(id=e), side, e,
                    ElementClass.PORCH, r["y0"], self._side(place, ring, r["x0"], r["x1"],
                                                             r["color"]), Enum("BASESLAB"))


    # ——— плиты: стены над крышей нижней части, перекрытия, крыша ———

    def _plate(self, points: list[Vec], normal: Vec, depth: float) -> tuple[Ref, Ref]:
        """Плоский многоугольник в объёме: размещение и профиль в его плоскости; выдавливание —
        на depth против normal."""
        p0, x, y, z = _frame(points, normal)
        ring = [(_dot(_sub(p, p0), x), _dot(_sub(p, p0), y)) for p in points]
        return self.w.place(self.building_place, p0, z, x), self.w.polygon(ring)

    def _joints(self) -> None:
        house = roof.roofs(self.sheet)
        if house is None:
            return
        color = self.pen.colors.get(PaletteRole.MAIN, self.cfg.library.fill.wall)
        for j, joint in enumerate(roof.joints(house)):
            high = house.parts[joint.high]
            for i, wall in enumerate(self._under_roof(high, joint, w) for w in joint.walls):
                place, profile = self._plate(wall, (*joint.normal, 0.0), 0.0)
                item = self.w.solid(profile, self.ifc.joint_wall_m, color)
                ref = self.w.product("IfcWall", f"joint{j}/{i}", self.ifc.names.joint_wall,
                                     place, self.w.shape([item]), None, Enum("STANDARD"))
                self.walls.append(ref)
                self.contained[self._storey_at(wall[0][2])].append(ref)

    def _dormers(self) -> None:
        """Слуховые окна (gf#457): лицо со щипцом и щёчки — IfcWall (стена, как стена дома, а не
        крыша), окно лица — IfcOpeningElement с IfcWindow, как у стены; крыша дормера — плиты
        IfcSlab ROOF в составе IfcRoof дома (`_roof_faces`): крыша у дома одна, её части — скаты."""
        for b in self.dormers:
            self._dormer_face(b)
            for i, cheek in enumerate(b.cheeks(), 1):
                place, profile = self._plate(cheek.points, (*cheek.outward, 0.0), 0.0)
                self._dormer_wall(b, f"cheek{i}", self.cfg.dormer.names.cheek, (place, profile))

    def _dormer_face(self, b: dormers.Built) -> None:
        """Лицо дормера: стена в плоскости лица, профиль — (s, z) по стене дома, окно — проём."""
        w, f = self.w, b.frame
        out = (-f.inward[0], -f.inward[1], 0.0)
        place = w.place(self.building_place, f.at(0.0, b.profile.d0, 0.0), out, (*f.u, 0.0))
        self._dormer_wall(b, "face", self.cfg.dormer.names.face, (place, w.polygon(b.face_ring)))
        s0, z0, s1, z1 = b.window
        e = Element(id=f"дормер {b.number}", cls=ElementClass.WINDOW, x_m=s0, y_m=z0,
                    w_m=s1 - s0, h_m=z1 - z0)
        self._opening(b.side, self.walls[-1], place, e)

    def _dormer_wall(self, b: dormers.Built, part: str, name: str,
                     shape: tuple[Ref, Ref]) -> None:
        """IfcWall дормера: профиль на толщину стены дома внутрь от плоскости куска."""
        w = self.w
        color = self.pen.colors.get(PaletteRole.MAIN, self.cfg.library.fill.wall)
        item = w.solid(shape[1], self.ifc.wall_thickness_m, color)
        key = f"dormer{b.number}/{part}"
        ref = w.product("IfcWall", key, name.format(n=b.number), shape[0], w.shape([item]), None,
                        Enum("STANDARD"))
        w.props(key, ref, "Pset_WallCommon", {"IsExternal": boolean(True)})
        self.walls.append(ref)
        self.contained[self._storey_at(b.profile.zb)].append(ref)

    def _under_roof(self, high: roof.Roofline, joint: roof.Joint, wall: list[Vec]) -> list[Vec]:
        """Стена над кровлей нижней части, выдавленная к высокой: верх не выше плиты кровли высокой
        (скат + толщина) на внутренней грани (там скат ниже) — иначе стена торчит над кровлей."""
        t = self.ifc.joint_wall_m
        out = list(wall)
        for i in (2, 3):
            x, y, z = wall[i]
            inner = high.height((x - joint.normal[0] * t, y - joint.normal[1] * t))
            cap = min(z, inner + self.roof_m) - self.ifc.roof_seat_m
            out[i] = (x, y, max(wall[3 - i][2], cap))
        return out

    def _footprint(self, k: int) -> shapely.Geometry:
        """Площадь перекрытия над этажом k: этажи части дома считает лист (`WallRun.floors`);
        внутренняя грань стен — контур минус толщина."""
        outline = shapely.Polygon(self.data["corners"])
        if parts.stepped(self.sheet):
            floors = {r.part: r.floors for f in self.sheet.facades for r in f.runs}
            rects = parts.parts_of(self.sheet, self.data["corners"])
            area = shapely.union_all([shapely.box(r.x0_m, r.y0_m, r.x1_m, r.y1_m)
                                      for j, r in enumerate(rects)
                                      if floors.get(j, self.sheet.spec.floors) > k])
            outline = outline.intersection(area)
        return outline.buffer(-self.ifc.wall_thickness_m, join_style="mitre")

    def _slabs(self) -> None:
        w, color = self.w, self.cfg.library.fill.other
        for k in range(self.sheet.spec.floors):
            shape = self._footprint(k)
            items = [w.solid(w.polygon(list(p.exterior.coords)[:-1]), self.ifc.slab_m, color)
                     for p in getattr(shape, "geoms", [shape]) if not p.is_empty]
            place = w.place(self.building_place, (0.0, 0.0, self.levels[k]))
            ref = w.product("IfcSlab", f"slab{k}", self.ifc.names.slab.format(n=k + 1), place,
                            w.shape(items), None, Enum("FLOOR"))
            self.contained[k].append(ref)

    def _roof(self) -> None:
        """Скаты — плиты по граням крыши, плоская крыша — плита по контуру (со свесом карниза)
        на карнизе; всё это части одного IfcRoof."""
        top = self.sheet.spec.floors - 1
        faces = self._roof_faces()
        slabs = []
        for n, (points, normal) in enumerate(faces, 1):
            place, profile = self._plate(points, normal, 0.0)
            _, x, y, z = _frame(points, normal)
            down = (_dot(DOWN, x), _dot(DOWN, y), _dot(DOWN, z))  # вертикаль в осях профиля
            item = self.w.solid_along(profile, down, self.roof_m, self._roof_color())
            slabs.append(self.w.product("IfcSlab", f"roofslab{n}", self.ifc.names.roof_slab.format(
                n=n), place, self.w.shape([item]), None, Enum("ROOF")))
        self.roof_slabs = slabs
        self.roof_ref = self.w.product("IfcRoof", "roof", self.ifc.names.roof, self.building_place,
                                       None, None, Enum("NOTDEFINED"))
        self.w.relate("IfcRelAggregates", "roof", self.roof_ref, slabs)
        self.contained[top].append(self.roof_ref)

    def _skylights(self) -> None:
        """Мансардные окна (gf#456): IfcWindow вида SKYLIGHT в плоскости ската — тело окна лежит в
        толще плиты кровли, на верху кровли с зазором `lift_m`. Выреза в плите нет: плита — грань
        без отверстий, а вырез по наклонной плоскости с вертикальными торцами вышел бы сложнее
        самого окна; плита под стеклом остаётся."""
        w, look, ifc = self.w, self.cfg.sheet.skylight, self.ifc
        top = self.sheet.spec.floors - 1
        for n, item in enumerate(skylights.find(self.sheet, look), 1):
            ring = skylights.raised(item, self.roof_m + look.lift_m).outer
            normal = _up(_normal(ring))
            place, profile = self._plate(ring, normal, 0.0)
            _, x, y, z = _frame(ring, normal)
            body = w.solid_along(profile, (_dot(DOWN, x), _dot(DOWN, y), _dot(DOWN, z)),
                                 self.roof_m, self.cfg.library.fill.glass, ifc.glass_transparency)
            window = w.product("IfcWindow", f"skylight/{n}", ifc.names.skylight.format(n=n), place,
                               w.shape([body]), None, look.length_m, look.width_m,
                               Enum("SKYLIGHT"), Enum("NOTDEFINED"), None)
            w.props(f"skylight/{n}", window, ifc.pset.facade, {"Id": label(f"skylight{n}")})
            w.props(f"skylight/{n}", window, COMMON[ElementClass.WINDOW],
                    {"IsExternal": boolean(True)})
            self.contained[top].append(window)

    def _roof_color(self) -> str:
        return self.pen.colors.get(self.pen.roof or "", self.cfg.viewer.house3d.roof)

    def _roof_faces(self) -> list[tuple[list[Vec], Vec]]:
        """Верхние многоугольники плит кровли и их нормали вверх: грань ската (низ плиты),
        поднятая на толщину по вертикали; плита плоской крыши — на толщину выше карниза. Плита
        выдавливается вниз по вертикали на толщину: низ — грань, торцы вертикальные (gf#447)."""
        house = roof.roofs(self.sheet)
        if house is not None:
            faces = self.faces + dormers.solids(self.dormers, 0.0)[dormers.Part.ROOF]
            return [([(x, y, z + self.roof_m) for x, y, z in face], _up(_normal(face)))
                    for face in faces]
        data = self.data["roof"]
        flat = [(shape["shape"], shape["height_m"]) for shape in data.get("slabs", [])]
        if data.get("flat"):
            flat.append((data["flat"], self.sheet.spec.eaves_m))
        return [([(x, y, h + self.roof_m) for x, y in shape], UP) for shape, h in flat]

    # ——— труба и водосток (gf#454): объекты крыши, которых нет у модели шага 4 ———

    def _roof_items(self) -> None:
        """Дымовая труба — IfcChimney (призма от низа в кровле до верха); желоб — IfcPipeSegment
        GUTTER, водосточная труба и её отвод — IfcPipeSegment RIGIDSEGMENT: брусок и цилиндры."""
        w, look = self.w, self.cfg.sheet.roof_items
        found = roof_items.roof_items(self.sheet, look)
        top = self.sheet.spec.floors - 1
        for n, c in enumerate(found.chimneys, 1):
            item = w.solid(w.polygon(c.footprint), c.z1 - c.z0, look.chimney_fill)
            ref = w.product("IfcChimney", f"chimney{n}", self.ifc.names.chimney.format(n=n),
                            w.place(self.building_place, (0.0, 0.0, c.z1)), w.shape([item]),
                            None, Enum("NOTDEFINED"))
            self.contained[top].append(ref)
        for n, g in enumerate(found.gutters, 1):
            self._segment(f"gutter{n}", self.ifc.names.gutter.format(n=n),
                          Bar("GUTTER", (g.a, g.b), g.z - g.size / 2, g.size, False))
        for n, p in enumerate(found.pipes, 1):
            name = self.ifc.names.pipe.format(n=n)
            item = w.solid(w.circle(p.diameter / 2), p.z_top, look.gutter_fill)
            ref = w.product("IfcPipeSegment", f"pipe{n}", name, w.place(
                self.building_place, (*p.center, p.z_top)), w.shape([item]), None,
                Enum("RIGIDSEGMENT"))
            self.contained[0].append(ref)
            if math.dist(p.elbow, p.center) > EPS:
                self._segment(f"elbow{n}", name, Bar("RIGIDSEGMENT", (p.center, p.elbow), p.z_top,
                                                    p.diameter, True))

    # ——— навес на столбах (gf#472) ———

    def _porch_roofs(self) -> None:
        """Навес — IfcRoof (SHED_ROOF, GABLE_ROOF, FLAT_ROOF): профиль кровли (вынос, высота),
        выдавленный вдоль стены; столбы — IfcColumn, призмы от земли до низа кровли."""
        w, look, names = self.w, self.cfg.sheet.porch_roof, self.ifc.names
        kinds = {RoofKind.SHED: "SHED_ROOF", RoofKind.GABLE: "GABLE_ROOF",
                 RoofKind.FLAT: "FLAT_ROOF"}
        for n, a in enumerate(porch_roofs.find(self.sheet, self.cfg.sheet), 1):
            # местные оси: x — наружу, z — против стены (против выдавливания, оно идёт вдоль −z)
            place = w.place(self.building_place, (*a.left, 0.0), (-a.u[0], -a.u[1], 0.0),
                            (*a.n, 0.0))
            item = w.solid(w.polygon(a.profile), a.length, self._roof_color())
            ref = w.product("IfcRoof", f"porchroof{n}", names.porch_roof.format(n=n), place,
                            w.shape([item]), None, Enum(kinds[a.kind]))
            self.awnings.append(ref)
            self.contained[self._storey_at(min(z for _, z in a.profile))].append(ref)
            for m, c in enumerate(a.posts, 1):
                self._post(f"{n}/{m}", a, c, look)

    def _post(self, key: str, a: porch_roofs.Awning, center: Point,
              look: PorchRoofLook) -> None:
        """Столб: квадрат сечения в плане, оси — наружу и вдоль стены, от низа кровли вниз."""
        w, half = self.w, a.post_m / 2
        corner = (center[0] - (a.n[0] + a.u[0]) * half, center[1] - (a.n[1] + a.u[1]) * half,
                  a.post_top)
        item = w.solid(w.rect(a.post_m, a.post_m), a.post_top, look.post_fill)
        ref = w.product("IfcColumn", f"porchpost{key}", self.ifc.names.porch_post.format(n=key),
                        w.place(self.building_place, corner, UP, (*a.n, 0.0)), w.shape([item]),
                        None, Enum("COLUMN"))
        self.contained[0].append(ref)

    def _segment(self, key: str, name: str, bar: Bar) -> None:
        """Труба или желоб по горизонтальной оси bar.ends на высоте оси bar.z."""
        w, (a, b), size = self.w, bar.ends, bar.size
        d = _unit((b[0] - a[0], b[1] - a[1], 0.0))
        x = (-d[1], d[0], 0.0)
        # размещение: ось z — вдоль a→b, выдавливание идёт назад по ней, от b к a
        at = (b[0], b[1], bar.z) if bar.round else (b[0] - x[0] * size / 2, b[1] - x[1] * size / 2,
                                                    bar.z - size / 2)
        profile = w.circle(size / 2) if bar.round else w.rect(size, size)
        item = w.solid(profile, math.dist(a, b), self.cfg.sheet.roof_items.gutter_fill)
        ref = w.product("IfcPipeSegment", key, name, w.place(self.building_place, at, d, x),
                        w.shape([item]), None, Enum(bar.kind))
        self.contained[0 if bar.round else self._storey_at(bar.z)].append(ref)

    # ——— материалы и этажи ———

    def _finish(self) -> None:
        w = self.w
        kinds = {m.id: m.kind for m in self.sheet.spec.materials}
        self._material(self.walls, kinds.get(PaletteRole.MAIN))
        self._material(self.roof_slabs + self.awnings, kinds.get(self.pen.roof or ""))
        for k, items in sorted(self.contained.items()):
            w.relate("IfcRelContainedInSpatialStructure", f"storey{k}", items, self.storeys[k])

    def _material(self, items: list[Ref], kind: str | None) -> None:
        if kind is None or not items:
            return
        material = self.w.s.add("IfcMaterial", kind, None, None)
        self.w.relate("IfcRelAssociatesMaterial", f"material/{kind}", items, material)
