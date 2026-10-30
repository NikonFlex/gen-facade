"""Величины фасада для метрик (gf#16): всё считается по листу, растр — только у SVD-метрики.

Этаж окна берётся по высоте его низа против отметок этажей дома, а не из поля `floor`:
поле пишет сам метод, и проверять его по нему же нельзя.
"""

from collections.abc import Callable
from itertools import combinations
from statistics import mean, pstdev

import numpy

from genfacade.config import Svd
from genfacade.schema import (
    EPS,
    Element,
    ElementClass,
    FacadeSheet,
    HouseSpec,
    SideFacade,
    ZoneRole,
)


def windows(f: SideFacade) -> list[Element]:
    return [e for e in f.elements if e.cls is ElementClass.WINDOW]


def floor_of(e: Element, spec: HouseSpec) -> int:
    """Этаж по низу элемента: 1 — ниже отметки второго этажа (и ниже цоколя), floors + 1 —
    выше карниза."""
    levels = spec.floor_levels()
    return 1 + sum(e.y_m + EPS >= level for level in levels[1:])


def level_of(e: Element, spec: HouseSpec) -> float:
    """Отметка пола этажа, на котором стоит элемент."""
    return spec.floor_levels()[min(floor_of(e, spec), spec.floors) - 1]


def _by_floor(f: SideFacade, spec: HouseSpec) -> list[list[Element]]:
    floors: dict[int, list[Element]] = {}
    for w in windows(f):
        floors.setdefault(floor_of(w, spec), []).append(w)
    return [sorted(ws, key=lambda e: e.x_m) for _, ws in sorted(floors.items())]


# ——— структура: величины стены, которые сравниваются с эталонным распределением ———

def top_spread(f: SideFacade, spec: HouseSpec) -> list[float]:
    """Разброс верха окон этажа в долях средней высоты окна (так мерили CMP, gf#16)."""
    out = []
    for ws in _by_floor(f, spec):
        if len(ws) > 1:
            tops = [w.y_m + w.h_m for w in ws]
            out.append((max(tops) - min(tops)) / mean(w.h_m for w in ws))
    return out


def axis_offset(f: SideFacade, spec: HouseSpec) -> list[float]:
    """Окно верхнего этажа: сдвиг центра от ближайшего окна этажа ниже в долях своей ширины."""
    floors, out = _by_floor(f, spec), []
    for low, high in zip(floors, floors[1:], strict=False):
        for w in high:
            c = w.x_m + w.w_m / 2
            out.append(min(abs(c - (v.x_m + v.w_m / 2)) for v in low) / w.w_m)
    return out


def gap_cv(f: SideFacade, spec: HouseSpec) -> list[float]:
    """Постоянство шага: коэффициент вариации простенков этажа, где окон три и больше."""
    out = []
    for ws in _by_floor(f, spec):
        gaps = [b.x_m - (a.x_m + a.w_m) for a, b in zip(ws, ws[1:], strict=False)]
        if len(gaps) > 1 and mean(gaps) > EPS:
            out.append(pstdev(gaps) / mean(gaps))
    return out


def sill_m(f: SideFacade, spec: HouseSpec) -> list[float]:
    return [w.y_m - level_of(w, spec) for w in windows(f)]


def head_m(f: SideFacade, spec: HouseSpec) -> list[float]:
    return [w.y_m + w.h_m - level_of(w, spec) for w in windows(f)]


def edge_share(f: SideFacade, spec: HouseSpec) -> list[float]:
    """Отступ окна от ближнего угла в долях длины стены."""
    length = f.side.length_m
    return [min(w.x_m, length - w.x_m - w.w_m) / length for w in windows(f)]


def width_m(f: SideFacade, spec: HouseSpec) -> list[float]:
    return [w.w_m for w in windows(f)]


def height_m(f: SideFacade, spec: HouseSpec) -> list[float]:
    return [w.h_m for w in windows(f)]


def windows_per_m(f: SideFacade, spec: HouseSpec) -> list[float]:
    return [len(windows(f)) / f.side.length_m]


STRUCTURE: dict[str, Callable[[SideFacade, HouseSpec], list[float]]] = {
    "top_spread": top_spread, "axis_offset": axis_offset, "gap_cv": gap_cv,
    "sill_m": sill_m, "head_m": head_m, "edge_share": edge_share,
    "width_m": width_m, "height_m": height_m, "windows_per_m": windows_per_m,
}


def structure(sheets: list[FacadeSheet]) -> dict[str, list[float]]:
    """Значения каждой величины по всем стенам всех домов."""
    return {name: [v for s in sheets for f in s.facades for v in measure(f, s.spec)]
            for name, measure in STRUCTURE.items()}


def wasserstein(a: list[float], b: list[float], points: int) -> float:
    """Расстояние Вассерштейна-1 между выборками: средняя разность их квантилей."""
    q = (numpy.arange(points) + 0.5) / points
    return float(numpy.mean(numpy.abs(numpy.quantile(a, q) - numpy.quantile(b, q))))


# ——— разнообразие ———

def features(f: SideFacade, spec: HouseSpec) -> list[float]:
    """Признаки раскладки стены: окон, средние ширина, высота и подоконник, доля остекления."""
    ws = windows(f)
    if not ws:
        return [0.0] * 5
    glass = sum(w.w_m * w.h_m for w in ws) / (f.side.length_m * spec.eaves_m)
    return [len(ws), mean(w.w_m for w in ws), mean(w.h_m for w in ws),
            mean(sill_m(f, spec)), glass]


# ——— соответствие описанию: требования текста, которые видны на чертеже ———

def floors_kept(sheet: FacadeSheet) -> bool:
    """Этажность видна по окнам: они только на этажах дома, и на верхнем этаже они есть.
    Дом без окон этажность не показывает — требование не выполнено."""
    found = {floor_of(w, sheet.spec) for f in sheet.facades for w in windows(f)}
    return found <= set(range(1, sheet.spec.floors + 1)) and sheet.spec.floors in found


def plinth_kept(sheet: FacadeSheet) -> bool:
    """Цоколь на каждой стене той высоты, что в параметрах дома."""
    return all(any(z.role is ZoneRole.PLINTH and
                   abs(max(y for _, y in z.shape) - sheet.spec.plinth_m) <= EPS for z in f.zones)
               for f in sheet.facades)


def palette_kept(sheet: FacadeSheet) -> bool:
    """Зона отделки — материалом палитры своей роли (у стаба и синтетики id материала — роль,
    `PaletteRole`); пояс палитрой не задан."""
    return all(z.material == z.role for f in sheet.facades for z in f.zones
               if z.role is not ZoneRole.BAND)


DESCRIPTION: dict[str, Callable[[FacadeSheet], bool]] = {
    "floors": floors_kept, "plinth": plinth_kept, "palette": palette_kept,
}


# ——— SVD-метрика Beyond Segmentation (вспомогательная) ———

def svd_score(f: SideFacade, spec: HouseSpec, cfg: Svd) -> float:
    """Взвешенная энергия неведущих сингулярных чисел маски окон (замкнутая форма,
    docs/metrics.md). Пустая маска и идеальная решётка — ноль: метрика вырождена."""
    rows, cols = round(spec.eaves_m * cfg.px_per_m), round(f.side.length_m * cfg.px_per_m)
    mask = numpy.zeros((rows, cols))
    for w in windows(f):
        x0, x1 = (round(v * cfg.px_per_m) for v in (w.x_m, w.x_m + w.w_m))
        y0, y1 = (round(v * cfg.px_per_m) for v in (w.y_m, w.y_m + w.h_m))
        mask[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)] = 1.0
    s = numpy.linalg.svd(mask, compute_uv=False)
    weights = numpy.minimum(numpy.arange(len(s)), cfg.k_max)
    return float(numpy.sum(weights * s ** 2) / mask.size)


def pairs(n: int, count: int, rng: numpy.random.Generator) -> list[tuple[int, int]]:
    """Все пары, если их не больше count, иначе count случайных."""
    if n * (n - 1) // 2 <= count:
        return list(combinations(range(n), 2))
    a, b = rng.integers(0, n, count), rng.integers(0, n - 1, count)
    return [(int(i), int(j + (j >= i))) for i, j in zip(a, b, strict=True)]
