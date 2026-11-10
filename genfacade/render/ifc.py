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

import shapely

from genfacade import parts, roof, unfold
from genfacade.config import Config
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

    def rect(self, w: float, h: float) -> Ref:
        centre = self.s.add("IfcAxis2Placement2D", self.s.add(
            "IfcCartesianPoint", [w / 2, h / 2]), None)
        return self.s.add("IfcRectangleProfileDef", Enum("AREA"), None, centre, w, h)

    def solid(self, profile: Ref, depth: float, color: str | None = None,
              transparency: float = 0.0) -> Ref:
        """Выдавливание профиля на depth вдоль −z местных осей; color — цвет, нет — без стиля."""
        item = self.s.add("IfcExtrudedAreaSolid", profile, self.axis((0.0, 0.0, 0.0)),
                          self.direction(DOWN), depth)
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
        self.levels = sheet.spec.floor_levels()
        self.storeys: list[Ref] = []
        self.contained: dict[int, list[Ref]] = defaultdict(list)  # этаж → объекты
        self.walls: list[Ref] = []
        self.roof_slabs: list[Ref] = []

    def build(self) -> str:
        self._structure()
        for k, f in enumerate(self.sheet.facades):
            self._wall(k, f)
        self._joints()
        self._slabs()
        self._roof()
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
        shapes = [shapely.Polygon(sil)]
        house = roof.roofs(self.sheet)
        if house is not None:
            shapes += [shapely.Polygon(p).buffer(0) for p in roof.house_above(house, k)]
        return shapely.union_all(shapes)

    def _trim(self, shape: shapely.Geometry, convex: bool) -> list[list[Point]]:
        """Профили стены с торцом у левого угла, сдвинутым на толщину: на выпуклом углу стена
        короче — угол занимает соседняя, на вогнутом длиннее — иначе в углу дыра в толщину."""
        shift = self.ifc.wall_thickness_m * (1 if convex else -1)
        rings = []
        for poly in getattr(shape, "geoms", [shape]):
            ring = list(poly.exterior.coords)[:-1]
            rings.append([(x + shift if abs(x) < EPS else x, y) for x, y in ring])
        return rings

    def _wall(self, k: int, f: SideFacade) -> None:
        w, t = self.w, self.ifc.wall_thickness_m
        wall = self.data["walls"][k]
        (lx, ly), (rx, ry) = wall["left"], wall["right"]
        u = _unit((rx - lx, ry - ly, 0.0))
        out = (u[1], -u[0], 0.0)
        place = w.place(self.building_place, (lx, ly, 0.0), out, u)
        color = self.pen.colors.get(PaletteRole.MAIN, self.cfg.library.fill.wall)
        items = [w.solid(w.polygon(ring), t, color)
                 for ring in self._trim(self._wall_shape(k, f), wall["convex_left"])]
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
        p0, z = points[0], _unit(normal)
        x = _unit(next(d for q in points[1:] if _length(d := _perp(_sub(q, p0), z)) > EPS))
        y = _cross(z, x)
        ring = [(_dot(_sub(p, p0), x), _dot(_sub(p, p0), y)) for p in points]
        return self.w.place(self.building_place, p0, z, x), self.w.polygon(ring)

    def _joints(self) -> None:
        house = roof.roofs(self.sheet)
        if house is None:
            return
        color = self.pen.colors.get(PaletteRole.MAIN, self.cfg.library.fill.wall)
        for j, joint in enumerate(roof.joints(house)):
            for i, wall in enumerate(joint.walls):
                place, profile = self._plate(wall, (*joint.normal, 0.0), 0.0)
                item = self.w.solid(profile, self.ifc.joint_wall_m, color)
                ref = self.w.product("IfcWall", f"joint{j}/{i}", self.ifc.names.joint_wall,
                                     place, self.w.shape([item]), None, Enum("STANDARD"))
                self.walls.append(ref)
                self.contained[self._storey_at(wall[0][2])].append(ref)

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
            item = self.w.solid(profile, self.ifc.roof_m, self._roof_color())
            slabs.append(self.w.product("IfcSlab", f"roofslab{n}", self.ifc.names.roof_slab.format(
                n=n), place, self.w.shape([item]), None, Enum("ROOF")))
        self.roof_slabs = slabs
        self.roof_ref = self.w.product("IfcRoof", "roof", self.ifc.names.roof, self.building_place,
                                       None, None, Enum("NOTDEFINED"))
        self.w.relate("IfcRelAggregates", "roof", self.roof_ref, slabs)
        self.contained[top].append(self.roof_ref)

    def _roof_color(self) -> str:
        return self.pen.colors.get(self.pen.roof or "", self.cfg.viewer.house3d.roof)

    def _roof_faces(self) -> list[tuple[list[Vec], Vec]]:
        """Многоугольники крыши и их нормали вверх. Плиты плоской крыши — выше карниза на
        толщину плиты: выдавливание идёт вниз и ложится на стены."""
        house = roof.roofs(self.sheet)
        if house is not None:
            return [(face, _up(_normal(face))) for face in roof.house_faces(house)]
        data = self.data["roof"]
        flat = [(shape["shape"], shape["height_m"]) for shape in data.get("slabs", [])]
        if data.get("flat"):
            flat.append((data["flat"], self.sheet.spec.eaves_m))
        return [([(x, y, h + self.ifc.roof_m) for x, y in shape], UP) for shape, h in flat]

    # ——— материалы и этажи ———

    def _finish(self) -> None:
        w = self.w
        kinds = {m.id: m.kind for m in self.sheet.spec.materials}
        self._material(self.walls, kinds.get(PaletteRole.MAIN))
        self._material(self.roof_slabs, kinds.get(self.pen.roof or ""))
        for k, items in sorted(self.contained.items()):
            w.relate("IfcRelContainedInSpatialStructure", f"storey{k}", items, self.storeys[k])

    def _material(self, items: list[Ref], kind: str | None) -> None:
        if kind is None or not items:
            return
        material = self.w.s.add("IfcMaterial", kind, None, None)
        self.w.relate("IfcRelAssociatesMaterial", f"material/{kind}", items, material)
