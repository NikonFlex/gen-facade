"""Дом объёмом для просмотра: стены по контуру плана, фасад стороны — текстурой, крыша плоская.

Это просмотр листа, а не 3D-модель для GenPlan: окна в 3D-конвертер — шаг 7, его делает Егор
(docs/decisions.md, 21.09 — «для демонстрации достаточно натянуть фасад на куб»). Координаты —
метры плана, y вверх. Сторона i идёт от угла i к углу i+1 по часовой; снаружи её левый край —
угол i+1, от него отсчитывается x фасада (как оси листа в render/svg.py).
"""

from genfacade.config import Config, House3d
from genfacade.render.svg import Pen, element_fill, facade_svg, pen_for
from genfacade.schema import Element, FacadeSheet, MaterialZone, SideFacade
from genfacade.unfold import plan_corners


def house_3d(sheet: FacadeSheet, cfg: Config) -> dict:
    """Углы контура, высота карниза и стены: края в плане, нормаль наружу, SVG фасада.
    Контур не ортогональный или не замкнут — PlanError из plan_corners."""
    corners = plan_corners([f.side for f in sheet.facades])
    pen = pen_for(sheet, cfg)
    walls = [{
        "side": f.side.index,
        "left": corners[(k + 1) % len(corners)],
        "right": corners[k],
        "normal": f.side.orientation,
        "length_m": f.side.length_m,
        "height_m": sheet.spec.eaves_m,
        "svg": facade_svg(_flat(f, cfg.viewer.house3d), pen),
        "relief": _relief(f, pen, cfg.viewer.house3d),
    } for k, f in enumerate(sheet.facades)]
    return {"corners": corners, "eaves_m": sheet.spec.eaves_m, "walls": walls}


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
    (карниз, подоконник, козырёк): рамка в метрах фасада, глубина и цвет листа."""
    boxes = [(z.shape, look.relief_role[z.role], pen.colors[z.material])
             for z in f.zones if _is_relief(z, look)]
    boxes += [([(e.x_m, e.y_m), (e.x_m + e.w_m, e.y_m + e.h_m)], look.relief_cls[e.cls],
               element_fill(e, pen)) for e in f.elements if _is_relief(e, look)]
    out = []
    for shape, depth, color in boxes:
        xs, ys = [x for x, _ in shape], [y for _, y in shape]
        out.append({"x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
                    "depth": depth, "color": color})
    return out
