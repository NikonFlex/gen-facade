"""Дом объёмом для просмотра: стены по контуру плана, фасад стороны — текстурой, крыша плоская.

Это просмотр листа, а не 3D-модель для GenPlan: окна в 3D-конвертер — шаг 7, его делает Егор
(docs/decisions.md, 21.09 — «для демонстрации достаточно натянуть фасад на куб»). Координаты —
метры плана, y вверх. Сторона i идёт от угла i к углу i+1 по часовой; снаружи её левый край —
угол i+1, от него отсчитывается x фасада (как оси листа в render/svg.py).
"""

from genfacade.config import Config
from genfacade.render.svg import Pen, facade_svg, palette_colors
from genfacade.schema import FacadeSheet
from genfacade.unfold import plan_corners


def house_3d(sheet: FacadeSheet, cfg: Config) -> dict:
    """Углы контура, высота карниза и стены: края в плане, нормаль наружу, SVG фасада.
    Контур не ортогональный или не замкнут — PlanError из plan_corners."""
    corners = plan_corners([f.side for f in sheet.facades])
    pen = Pen(cfg, palette_colors(sheet.spec, cfg))
    walls = [{
        "side": f.side.index,
        "left": corners[(k + 1) % len(corners)],
        "right": corners[k],
        "normal": f.side.orientation,
        "length_m": f.side.length_m,
        "height_m": sheet.spec.eaves_m,
        "svg": facade_svg(f, pen),
    } for k, f in enumerate(sheet.facades)]
    return {"corners": corners, "eaves_m": sheet.spec.eaves_m, "walls": walls}
