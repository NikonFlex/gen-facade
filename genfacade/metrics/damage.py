"""Что готовый векторизатор сделал со структурой эталона (gf#17): элементы эталонной стены против
элементов, которые нашёл векторизатор, по классам окно и дверь.

Для каждого элемента эталона берётся лучший по IoU элемент векторизатора любого класса:
- matched — тот же класс, IoU от `match_iou`;
- wrong_class — IoU от `match_iou`, но класс другой;
- merged — совпадения нет, зато эталонный элемент в основном внутри более крупного элемента того
  же класса (соседние окна слиты в одну область);
- split — совпадения нет, зато внутри эталонного элемента два и больше элементов того же класса
  (окно раздроблено);
- partial — совпадения нет, внутри один осколок того же класса (рамка съехала или усохла);
- lost — ничего похожего.
Лишние — элементы векторизатора класса без пары в эталоне (spurious) и сколько их всего (vec).
Выравнивание: доля окон, у которых на стене есть окно с тем же низом (ряд) и окно с тем же левым
краем на другом этаже (ось), с допуском `align_px` пикселей растра — у эталона и у векторизатора
одним правилом; ошибка рамки matched — средний сдвиг четырёх краёв, см.
"""

from collections import Counter

from genfacade.config import Config
from genfacade.schema import Element, ElementClass, FacadeSheet, SideFacade

CLASSES = (ElementClass.WINDOW, ElementClass.DOOR)
CM = 100.0


def iou(a: Element, b: Element) -> float:
    w = min(a.x_m + a.w_m, b.x_m + b.w_m) - max(a.x_m, b.x_m)
    h = min(a.y_m + a.h_m, b.y_m + b.h_m) - max(a.y_m, b.y_m)
    inter = max(w, 0.0) * max(h, 0.0)
    return inter / (a.w_m * a.h_m + b.w_m * b.h_m - inter)


def inside(part: Element, whole: Element) -> bool:
    """Больше половины площади `part` внутри `whole`."""
    w = min(part.x_m + part.w_m, whole.x_m + whole.w_m) - max(part.x_m, whole.x_m)
    h = min(part.y_m + part.h_m, whole.y_m + whole.h_m) - max(part.y_m, whole.y_m)
    return max(w, 0.0) * max(h, 0.0) > part.w_m * part.h_m / 2


def outcome(ref: Element, found: list[Element], threshold: float) -> str:
    """Что стало с элементом эталона среди найденных."""
    best = max(found, key=lambda e: iou(ref, e), default=None)
    if best is not None and iou(ref, best) >= threshold:
        return "matched" if best.cls is ref.cls else "wrong_class"
    if any(e.cls is ref.cls and inside(ref, e) for e in found):
        return "merged"
    pieces = [e for e in found if e.cls is ref.cls and inside(e, ref)]
    return "split" if len(pieces) > 1 else "partial" if pieces else "lost"


def edge_error_cm(ref: Element, found: Element) -> float:
    """Средний сдвиг четырёх краёв рамки, см."""
    edges = (ref.x_m - found.x_m, ref.x_m + ref.w_m - found.x_m - found.w_m,
             ref.y_m - found.y_m, ref.y_m + ref.h_m - found.y_m - found.h_m)
    return sum(abs(d) for d in edges) / 4 * CM


def wall(ref: list[Element], found: list[Element], threshold: float) -> Counter:
    """Счётчики одной стены: исходы эталонных элементов по классам, лишние, сумма ошибки рамки."""
    out: Counter = Counter()
    for cls in CLASSES:
        theirs = [e for e in found if e.cls is cls]
        mine = [e for e in ref if e.cls is cls]
        out[f"{cls}.ref"], out[f"{cls}.vec"] = len(mine), len(theirs)
        for r in mine:
            result = outcome(r, found, threshold)
            out[f"{cls}.{result}"] += 1
            if result == "matched":
                out[f"{cls}.edge_cm"] += edge_error_cm(r, max(theirs, key=lambda e: iou(r, e)))
        out[f"{cls}.spurious"] = sum(all(iou(r, e) < threshold for r in ref) for e in theirs)
    return out


def aligned(windows: list[Element], tol: float) -> Counter:
    """Окон с парой в ряду (тот же низ) и на оси (тот же левый край, другой этаж)."""
    out: Counter = Counter(windows=len(windows))
    for w in windows:
        others = [o for o in windows if o is not w]
        out["row"] += any(abs(o.y_m - w.y_m) <= tol for o in others)
        out["axis"] += any(abs(o.x_m - w.x_m) <= tol and o.floor != w.floor for o in others)
    return out


def elements_of(f: SideFacade) -> list[Element]:
    return [e for e in f.elements if e.cls in CLASSES]


def report(real: dict[str, FacadeSheet], seen: dict[str, list[list[Element]]],
           found: dict[str, list[list[Element]]], cfg: Config) -> dict:
    """Суммы по домам, которые векторизатор успел: исходы эталонных элементов `seen` (видимых на
    растре), лишние, ошибка рамки, выравнивание у эталона (`ref_*`) и у векторизатора (`vec_*`)."""
    run, total = cfg.baselines.vectorizer, Counter()
    for name, walls in found.items():
        sheet = real[name]
        for f, ref, got in zip(sheet.facades, seen[name], walls, strict=True):
            total += wall(ref, got, run.match_iou)
            tol = run.align_px * max(f.side.length_m, sheet.spec.eaves_m) / run.long_side_px
            for key, items in (("ref", ref), ("vec", got)):
                windows = [e for e in items if e.cls is ElementClass.WINDOW]
                total += Counter({f"{key}_{k}": v for k, v in aligned(windows, tol).items()})
    return {"houses": len(found), **dict(sorted(total.items()))}
