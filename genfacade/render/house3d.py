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

from genfacade import roof, window_shape
from genfacade.config import Config, House3d
from genfacade.derive import DERIVED
from genfacade.render.svg import Pen, element_fill, facade_svg, pen_for
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    MaterialZone,
    PaletteRole,
    Point,
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
        "height_m": sheet.spec.eaves_m,
        "svg": facade_svg(_flat(f, look), pen),
        "relief": _relief(f, pen, look),
    } for k, f in enumerate(sheet.facades)]
    return {"corners": corners, "eaves_m": sheet.spec.eaves_m,
            "trim": cfg.sheet.trim.model_dump(), "walls": walls,
            "roof": _roof(sheet, pen, corners, look)}


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
    Цвет кровли — материала крыши, если он в палитре (нет — цвет крыши просмотра)."""
    line = roof.roofline(sheet)
    if line is None:
        cornice = any(e.cls is ElementClass.CORNICE for f in sheet.facades for e in f.elements)
        out = look.relief_cls.get(ElementClass.CORNICE, 0.0) if cornice else 0.0
        flat = shapely.Polygon(corners).buffer(out, join_style="mitre") if out else None
        return {"faces": [], "above": [], "color": None, "wall": None, "windows": [],
                "flat": list(flat.exterior.coords)[:-1] if flat else corners}
    above, windows = [], []
    for k, f in enumerate(sheet.facades):
        if (shape := roof.above_eaves(line, k)) is not None:
            left, u, _ = roof.wall_axis(line, k)
            above.append([(left[0] + u[0] * x, left[1] + u[1] * x, y) for x, y in shape])
            windows += _gable_windows(f, line, k, look, pen.cfg.checks.slope_offset_m)
    return {"faces": [face for _, face in roof.faces(line)], "above": above, "flat": None,
            "color": pen.colors.get(pen.roof or ""), "wall": pen.colors.get(PaletteRole.MAIN),
            "windows": windows, "glass": pen.cfg.library.fill.glass}


def _gable_windows(f: SideFacade, line: roof.Roofline, k: int, look: House3d,
                   offset: float) -> list[list]:
    """Окна во фронтоне (gf#321) в объёме: часть рамки выше карниза — текстура стены кончается на
    карнизе, а фронтон — гладкий многоугольник; чуть наружу от стены, чтобы не тонуть в ней."""
    left, u, _ = roof.wall_axis(line, k)
    out = (u[1] * look.window_out_m, -u[0] * look.window_out_m)  # наружная нормаль стены
    quads = []
    room = roof.room(f.side.length_m, line.eaves, roof.above_eaves(line, k),
                     offset)
    above = shapely.box(-roof.FAR, line.eaves, roof.FAR, roof.FAR)
    for e in f.elements:
        if roof.over_eaves(e, line.eaves):
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
            + [_element_relief(e, pen, look) for e in f.elements if _is_relief(e, look)])


def _frame(shape: list[Point], depth: float, color: str) -> dict:
    xs, ys = [x for x, _ in shape], [y for _, y in shape]
    return {"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys), "depth": depth,
            "color": color}


def _zone_relief(z: MaterialZone, pen: Pen, look: House3d) -> dict:
    return _frame(z.shape, look.relief_role[z.role], pen.colors[z.material]) | {
        "role": z.role, "cls": None, "kind": None, "steps": None}


def _element_relief(e: Element, pen: Pen, look: House3d) -> dict:
    """Вид — козырька и подоконника у дома (`HouseSpec.trim`), число ступеней — у крыльца."""
    shape = [(e.x_m, e.y_m), (e.x_m + e.w_m, e.y_m + e.h_m)]
    kind = pen.trim.kind(TRIM_OF[e.cls]) if e.cls in TRIM_OF else None
    return _frame(shape, look.relief_cls[e.cls], element_fill(e, pen)) | {
        "role": None, "cls": e.cls, "kind": kind, "steps": _steps(e, look)}


def porch_steps(height_m: float, look: House3d) -> int:
    """Ступеней у крыльца: высота / высота ступени вверх, не меньше одной. Допуск EPS: 0,51 м при
    ступени 0,17 м — ровно три, а не четыре из-за двоичной дроби."""
    return max(1, math.ceil(height_m / look.riser_m - EPS))


def _steps(e: Element, look: House3d) -> int | None:
    return porch_steps(e.h_m, look) if e.cls is ElementClass.PORCH else None
