"""Дом объёмом для просмотра: стены по контуру плана, фасад стороны — текстурой, крыша — скатами
из roof.py (над прямоугольным домом, gf#320) или плоская, стена над карнизом — цветом стены;
выступы (цоколь, карниз, подоконник, козырёк, крыльцо) идут отдельно и несут класс и вид — форму
по ним строит viewer/static/house3d_relief.js (gf#305).

Это просмотр листа, а не 3D-модель для GenPlan: окна в 3D-конвертер — шаг 7, его делает Егор
(docs/decisions.md, 21.09 — «для демонстрации достаточно натянуть фасад на куб»). Координаты —
метры плана, y вверх. Сторона i идёт от угла i к углу i+1 по часовой; снаружи её левый край —
угол i+1, от него отсчитывается x фасада (как оси листа в render/svg.py).
"""

import math

import shapely

from genfacade import parts, roof, roof_items, window_shape
from genfacade.config import Config, House3d
from genfacade.derive import DERIVED
from genfacade.render.svg import (
    Pen,
    element_fill,
    element_material,
    facade_svg,
    foot_of,
    pen_for,
    swatch,
)
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    MaterialZone,
    PaletteRole,
    Point,
    Polygon,
    SideFacade,
    signed_area,
)
from genfacade.unfold import plan_corners

TRIM_OF = {cls: trim for trim, cls in DERIVED.items()}  # класс выводимого элемента → его вид у дома


def house_3d(sheet: FacadeSheet, cfg: Config) -> dict:
    """Углы контура, высота карниза и стены: края в плане, нормаль наружу, выпуклость левого угла,
    SVG фасада. Контур не ортогональный или не замкнут — PlanError из plan_corners."""
    corners = plan_corners([f.side for f in sheet.facades])
    pen = pen_for(sheet, cfg)
    look = _look(sheet, cfg.viewer.house3d)
    walls = [{
        "side": f.side.index,
        "left": corners[(k + 1) % len(corners)],
        "right": corners[k],
        "normal": f.side.orientation,
        "length_m": f.side.length_m,
        "convex_left": _convex(corners, (k + 1) % len(corners)),
        "height_m": max((y for _, y in f.silhouette or []), default=sheet.spec.eaves_m),
        # Силуэт стены (x от левого края, высота): обводка — по нему, а не по прямоугольнику
        # текстуры, иначе у стены со ступенью рамка висит над нижней частью (gf#431). Нет — рамка.
        "outline": f.silhouette,
        "svg": facade_svg(_flat(f, look), pen),
        "relief": _relief(f, pen, look),
    } for k, f in enumerate(sheet.facades)]
    roof_part = _roof(sheet, pen, corners, look)
    used = {r["material"] for w in walls for r in w["relief"]} | {
        roof_part["material"], roof_part["wall_material"]}
    swatches = {m: s for m in used - {None} if (s := swatch(m, pen)) is not None}
    return {"corners": corners, "eaves_m": sheet.spec.eaves_m,
            "trim": cfg.sheet.trim.model_dump(), "walls": walls, "roof": roof_part,
            "items": _items(sheet, cfg), "swatches": swatches}


def _items(sheet: FacadeSheet, cfg: Config) -> dict:
    """Труба и водосток в объёме (gf#454): метры плана и высота; труба — призма по четырём углам,
    желоб — брусок по оси, водосточная труба — цилиндр и отвод к желобу."""
    look = cfg.sheet.roof_items
    found = roof_items.roof_items(sheet, look)
    chimney = found.chimney
    return {
        "chimney": None if chimney is None else {
            "footprint": chimney.footprint, "z0": chimney.z0, "z1": chimney.z1,
            "color": look.chimney_fill},
        "gutters": [{"a": g.a, "b": g.b, "z": g.z, "size": g.size, "color": look.gutter_fill}
                    for g in found.gutters],
        "pipes": [{"center": p.center, "elbow": p.elbow, "z_top": p.z_top,
                   "diameter": p.diameter, "color": look.gutter_fill} for p in found.pipes]}


def _look(sheet: FacadeSheet, look: House3d) -> House3d:
    """Выступы дома: под скатной кровлей карниз — полоса на стене под свесом, а не коробка: у
    кровли от края стены уклон вниз, и выступ на отметке карниза прошёл бы сквозь свес (хозяин
    07.11: «карниз выпирает за крышу», gf#320)."""
    if not roof.builds(sheet):
        return look
    return look.model_copy(update={"relief_cls": {
        cls: depth for cls, depth in look.relief_cls.items() if cls != ElementClass.CORNICE}})


def _roof(sheet: FacadeSheet, pen: Pen, corners: list[Point], look: House3d) -> dict:
    """Скаты и стены над карнизом в объёме: многоугольники (x, y плана, высота) и цвета; скаты
    не строятся — пусто, просмотр кладёт плоскую крышу по контуру `flat`: он шире плана на вынос
    карниза, если карниз на доме есть, — плита закрывает его сверху, а не он торчит из-под неё.
    Цвет кровли — материала крыши, если он в палитре (нет — цвет крыши просмотра). `material` и
    `wall_material` — id материалов кровли и стены над карнизом: рисунком их выкладывает 3D
    (gf#353, `swatches` дома); материала нет в палитре — None. У дома из частей (gf#322) плиты
    частей — того же материала кровли. `thickness_m` — толщина кровли: низ плиты — грань ската или
    уровень карниза, верх — выше на неё по вертикали (gf#447)."""
    data = _roof_shape(sheet, pen, corners, look)
    data["thickness_m"] = pen.cfg.sheet.roof.thickness_m  # одна на лист, 3D и IFC (gf#447)
    return data


def _roof_shape(sheet: FacadeSheet, pen: Pen, corners: list[Point], look: House3d) -> dict:
    house = roof.roofs(sheet)
    material = pen.roof if pen.roof in pen.colors else None
    wall_material = PaletteRole.MAIN if PaletteRole.MAIN in pen.colors else None
    if house is None and parts.stepped(sheet):
        slabs = [{"shape": shape, "height_m": h} for shape, h in parts.slabs(sheet, corners)]
        return {"faces": [], "above": [], "color": pen.colors.get(pen.roof or ""),
                "wall": pen.colors.get(PaletteRole.MAIN), "flat": None, "slabs": slabs,
                "material": material, "wall_material": wall_material}
    if house is None:
        cornice = any(e.cls is ElementClass.CORNICE for f in sheet.facades for e in f.elements)
        out = look.relief_cls.get(ElementClass.CORNICE, 0.0) if cornice else 0.0
        flat = shapely.Polygon(corners).buffer(out, join_style="mitre") if out else None
        return {"faces": [], "above": [], "color": None, "wall": None, "windows": [],
                "material": None, "wall_material": None,
                "flat": list(flat.exterior.coords)[:-1] if flat else corners}
    zones = roof.sheet_gables(sheet)  # окна во фронтоне (gf#321, gf#453) — в зоне листа
    above, windows = [], []
    for k, f in enumerate(sheet.facades):
        left, u, _ = roof.axis(house.corners, k)
        for shape in roof.house_above(house, k):
            above.append([(left[0] + u[0] * x, left[1] + u[1] * x, y) for x, y in shape])
        if zones[k] is not None:
            windows += _gable_windows(f, (left, u), zones[k], sheet.spec.eaves_m, look,
                                      pen.cfg.checks.slope_offset_m)
    above += [wall for joint in roof.joints(house) for wall in joint.walls]
    return {"faces": roof.house_faces(house), "above": above, "flat": None,
            "color": pen.colors.get(pen.roof or ""), "wall": pen.colors.get(PaletteRole.MAIN),
            "material": material, "wall_material": wall_material,
            "windows": windows, "glass": pen.cfg.library.fill.glass}


def _gable_windows(f: SideFacade, axis: tuple[Point, Point], zone: Polygon, eaves: float,
                   look: House3d, offset: float) -> list[list]:
    """Окна во фронтоне (gf#321) в объёме: часть рамки выше карниза — текстура стены кончается на
    карнизе, а фронтон — гладкий многоугольник; чуть наружу от стены, чтобы не тонуть в ней."""
    left, u = axis
    out = (u[1] * look.window_out_m, -u[0] * look.window_out_m)  # наружная нормаль стены
    quads = []
    room = roof.room(f.side.length_m, eaves, zone, offset)
    above = shapely.box(-roof.FAR, eaves, roof.FAR, roof.FAR)
    for e in f.elements:
        if roof.over_eaves(e, eaves):
            # контур по виду окна (gf#319), выше карниза — ниже он в текстуре стены
            part = shapely.Polygon(window_shape.outline(e, room)).intersection(above)
            if part.is_empty or part.geom_type != "Polygon":
                continue
            quads.append([(left[0] + u[0] * x + out[0], left[1] + u[1] * x + out[1], y)
                          for x, y in list(part.exterior.coords)[:-1]])
    return quads


def _convex(corners: list[Point], k: int) -> bool:
    """Выпуклый ли угол k контура: контур идёт по часовой (площадь отрицательна), и на выпуклом
    угле он поворачивает вправо. От этого зависит стык выступов соседних стен."""
    (px, py), (cx, cy), (nx, ny) = corners[k - 1], corners[k], corners[(k + 1) % len(corners)]
    return ((cx - px) * (ny - cy) - (cy - py) * (nx - cx)) * signed_area(corners) > 0


def _is_relief(item: MaterialZone | Element, look: House3d) -> bool:
    """Идёт ли зона (роль) или элемент (класс) выступом: один список на текстуру и на коробки."""
    if isinstance(item, MaterialZone):
        return item.role in look.relief_role
    return item.cls in look.relief_cls


def _flat(f: SideFacade, look: House3d) -> SideFacade:
    """Стена для текстуры — без того, что 3D ставит выступом: иначе оно рисуется дважды, плоско
    на стене и коробкой перед ней, и под углом видны оба со сдвигом (gf#277). На листе
    фасадов (render/svg.sheet_svg) выступающее остаётся."""
    return f.model_copy(update={
        "zones": [z for z in f.zones if not _is_relief(z, look)],
        "elements": [e for e in f.elements if not _is_relief(e, look)]})


def _relief(f: SideFacade, pen: Pen, look: House3d) -> list[dict]:
    """Выступы стены — зоны ролей `relief_role` (цоколь) и элементы классов `relief_cls`
    (карниз, подоконник, козырёк, крыльцо): рамка в метрах фасада, глубина, цвет листа, класс
    и вид — форму по ним строит просмотр."""
    return ([_zone_relief(z, pen, look) for z in f.zones if _is_relief(z, look)]
            + [_element_relief(e, pen, look, foot_of(e, f.elements)) for e in f.elements
               if _is_relief(e, look)])


def _frame(shape: list[Point], depth: float, color: str, material: str | None) -> dict:
    """material — материал палитры, залитый рисунком на листе, или None (красим цветом)."""
    xs, ys = [x for x, _ in shape], [y for _, y in shape]
    return {"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "depth": depth,
            "color": color, "material": material}


def _zone_relief(z: MaterialZone, pen: Pen, look: House3d) -> dict:
    return _frame(z.shape, look.relief_role[z.role], pen.colors[z.material], z.material) | {
        "role": z.role, "cls": None, "shape": None, "steps": None, "foot": None}


def _element_relief(e: Element, pen: Pen, look: House3d, foot: float) -> dict:
    """Форма — козырька и подоконника по виду дома (`HouseSpec.trim`, запись derive.toml: форму
    строит просмотр по её имени), число ступеней — у крыльца."""
    shape = [(e.x_m, e.y_m), (e.x_m + e.w_m, e.y_m + e.h_m)]
    trim = TRIM_OF.get(e.cls)
    form = pen.cfg.derive.find(trim, pen.trim.kind(trim)) if trim is not None else None
    return _frame(shape, look.relief_cls[e.cls], element_fill(e, pen), element_material(e, pen)) | {
        "role": None, "cls": e.cls, "id": e.id, "shape": form.shape if form else None,
        "steps": _steps(e, look), "foot": foot}


def porch_steps(height_m: float, look: House3d) -> int:
    """Ступеней у крыльца: высота / высота ступени вверх, не меньше одной. Допуск EPS: 0,51 м при
    ступени 0,17 м — ровно три, а не четыре из-за двоичной дроби."""
    return max(1, math.ceil(height_m / look.riser_m - EPS))


def _steps(e: Element, look: House3d) -> int | None:
    return porch_steps(e.h_m, look) if e.cls is ElementClass.PORCH else None
