"""Сверка разметки дома с эталоном по видам полей (gf#470).

    python tools/markup_compare.py <папка эталона> <папка проверяемых> [-o отчёт.md] [--json]

Дома — по совпадению имени файла. Поля дома: совпало, нет или нет в одном из двух (числа — с
допуском из `config/data.toml`, [manual.compare]); списки — по числу. Окна и двери — по сторонам
(по порядку): рамки в метры стены (`manual._metres`), жадно по IoU, класс должен совпасть.
"""

import argparse
import json
import math
import statistics
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from genfacade.config import MarkupCompare, load  # noqa: E402
from genfacade.datasets import manual  # noqa: E402
from genfacade.datasets.manual import Markup  # noqa: E402
from genfacade.schema import EPS, OPENINGS, ElementClass, HouseSpec  # noqa: E402
from tools.owl_boxes import overlap  # noqa: E402

SCALARS = ("roof_kind", "roof_material", "material", "plinth_material", "trim_material", "gutters",
           "overhang_by")
TRIM_KINDS = ("sill", "casing", "shutters", "canopy", "door")
NUMBERS = {"pitch_deg": "tol_pitch_deg", "overhang_m": "tol_overhang_m",
           "gable_overhang_m": "tol_overhang_m", "plinth": "tol_plinth_m"}
FLOORS = "floor_heights"
COUNTS = ("chimneys", "skylights", "dormers", "porch_roofs", "part_roofs")
PERCENTILE = 0.9
NONE = "—"
# Отметка y нужна от чистого пола, а `_metres` считает от земли: цоколь для неё — ноль.
FLOOR_LEVEL = HouseSpec.model_construct(plinth_m=0.0)

Box = tuple[float, float, float, float]


class Status(StrEnum):
    SAME = "same"
    DIFF = "diff"
    MISSING = "missing"  # значение есть только в одном из двух


@dataclass(frozen=True)
class Entry:
    row: str       # строка сводной таблицы
    value: object
    tol: float | None = None


@dataclass(frozen=True)
class Diff:
    row: str
    label: str
    ref: object
    got: object
    status: Status


@dataclass
class Openings:
    ref: int = 0
    found: int = 0
    extra: int = 0
    dx: list[float] = field(default_factory=list)
    dw: list[float] = field(default_factory=list)


@dataclass
class House:
    name: str
    diffs: list[Diff] = field(default_factory=list)
    openings: Openings | None = None  # None — стороны не сверялись
    error: str | None = None
    absent: bool = False


def _entries(m: Markup, floors: int, tol: MarkupCompare) -> dict[str, Entry]:
    out = {name: Entry(name, getattr(m, name)) for name in SCALARS}
    out |= {f"trim.{k}": Entry("trim", m.trim.kind(k)) for k in TRIM_KINDS}
    out |= {name: Entry(name, getattr(m, name), getattr(tol, attr))
            for name, attr in NUMBERS.items()}
    out |= {f"{FLOORS}[{i}]": Entry(FLOORS, m.floor_heights[i], tol.tol_floor_m)
            for i in range(floors)}
    out["floors"] = Entry("floors", len(m.floor_heights))
    out |= {name: Entry(name, len(getattr(m, name))) for name in COUNTS}
    out["sides"] = Entry("sides", len(m.sides))
    return out


def _status(ref: object, got: object, tol: float | None) -> Status:
    if (ref is None) != (got is None):
        return Status.MISSING
    if tol is None or ref is None or got is None:
        return Status.SAME if ref == got else Status.DIFF
    return Status.SAME if abs(ref - got) <= tol + EPS else Status.DIFF


def compare_fields(ref: Markup, got: Markup, tol: MarkupCompare) -> list[Diff]:
    floors = min(len(ref.floor_heights), len(got.floor_heights))
    a, b = _entries(ref, floors, tol), _entries(got, floors, tol)
    return [Diff(e.row, label, e.value, b[label].value, _status(e.value, b[label].value, e.tol))
            for label, e in a.items()]


def _boxes(m: Markup, e: manual.Elevation) -> list[tuple[ElementClass, Box]]:
    return [(x.cls, manual._metres(x.box, e, m, FLOOR_LEVEL))
            for x in e.elements if x.cls in OPENINGS]


def _match(ref: list[tuple[ElementClass, Box]], got: list[tuple[ElementClass, Box]],
           iou_min: float) -> list[tuple[int, int]]:
    """Жадно: пары одного класса по убыванию IoU, каждая рамка — в одной паре."""
    scored = sorted(((overlap(r[1], g[1])[1], i, j) for i, r in enumerate(ref)
                     for j, g in enumerate(got) if r[0] is g[0]), reverse=True)
    used_i, used_j, pairs = set(), set(), []
    for score, i, j in scored:
        if score >= iou_min and i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            pairs.append((i, j))
    return pairs


def _add_side(acc: Openings, ref: list, got: list, iou_min: float) -> None:
    pairs = _match(ref, got, iou_min)
    acc.ref += len(ref)
    acc.found += len(pairs)
    acc.extra += len(got) - len(pairs)
    for i, j in pairs:
        a, b = ref[i][1], got[j][1]
        acc.dx.append(abs((a[0] + a[2]) / 2 - (b[0] + b[2]) / 2))
        acc.dw.append(abs((a[2] - a[0]) - (b[2] - b[0])))


def compare_openings(ref: Markup, got: Markup, iou_min: float) -> Openings:
    acc = Openings()
    for er, eg in zip(ref.sides, got.sides, strict=True):
        _add_side(acc, _boxes(ref, er), _boxes(got, eg), iou_min)
    return acc


def compare_house(name: str, ref: Markup, got: Markup, tol: MarkupCompare) -> House:
    same_sides = len(ref.sides) == len(got.sides)
    return House(name, compare_fields(ref, got, tol),
                 compare_openings(ref, got, tol.iou_min) if same_sides else None)


def _read(path: Path) -> tuple[Markup | None, str | None]:
    try:
        return manual.read(path), None
    except (ValueError, OSError) as e:  # TOML, схема и чтение файла
        return None, f"{path.name}: {str(e).splitlines()[0]}"


def compare_dirs(ref_dir: Path, got_dir: Path, tol: MarkupCompare) -> list[House]:
    out = []
    for path in sorted(ref_dir.glob("*.toml")):
        other = got_dir / path.name
        if not other.exists():
            out.append(House(path.stem, absent=True))
            continue
        (ref, bad_ref), (got, bad_got) = _read(path), _read(other)
        if ref is None or got is None:
            out.append(House(path.stem, error=bad_ref or bad_got))
        else:
            out.append(compare_house(path.stem, ref, got, tol))
    return out


def totals(houses: list[House]) -> dict[str, list[int]]:
    """Строка таблицы → [совпало, всего] по домам, которые сверялись."""
    same, total = Counter(), Counter()
    for h in houses:
        for d in h.diffs:
            total[d.row] += 1
            same[d.row] += d.status is Status.SAME
    return {name: [same[name], total[name]] for name in total}


def _pct(a: int, b: int) -> str:
    return f"{a} из {b} ({100 * a / b:.0f} %)" if b else NONE


def _p90(xs: list[float]) -> float:
    return sorted(xs)[math.ceil(PERCENTILE * len(xs)) - 1]


def _error_cells(xs: list[float]) -> str:
    return f"{statistics.median(xs):.3f} | {_p90(xs):.3f}" if xs else f"{NONE} | {NONE}"


def _show(v: object) -> str:
    return NONE if v is None else f"{v:g}" if isinstance(v, float) else str(v)


def _diff_text(d: Diff) -> str:
    sep = " / " if d.status is Status.MISSING else " → "
    return f"{d.label} {_show(d.ref)}{sep}{_show(d.got)}"


def _house_line(h: House) -> str:
    if h.absent:
        return f"- **{h.name}**: не размечен"
    if h.error:
        return f"- **{h.name}**: ошибка чтения — {h.error}"
    parts = [_diff_text(d) for d in h.diffs if d.status is not Status.SAME]
    o = h.openings
    if o is None:
        parts.append("стороны не сверены (число сторон разное)")
    elif o.found < o.ref or o.extra:
        parts.append(f"окна и двери: найдено {o.found} из {o.ref}, лишних {o.extra}")
    return f"- **{h.name}**: " + ("; ".join(parts) or "расхождений нет")


def _merged(houses: list[House]) -> Openings:
    acc = Openings()
    for o in (h.openings for h in houses if h.openings):
        acc.ref += o.ref
        acc.found += o.found
        acc.extra += o.extra
        acc.dx += o.dx
        acc.dw += o.dw
    return acc


def render(houses: list[House], ref_dir: Path, got_dir: Path) -> str:
    checked = [h for h in houses if h.diffs]
    o = _merged(checked)
    lines = [f"# Сверка разметки: {got_dir} с эталоном {ref_dir}", "",
             f"Домов в эталоне {len(houses)}, сверено {len(checked)}.", "",
             "## Поля дома", "", "| поле | совпало |", "|---|---|"]
    lines += [f"| {n} | {_pct(*t)} |" for n, t in totals(checked).items()]
    lines += ["", "## Окна и двери", "", "| | |", "|---|---|",
              f"| найдено из эталона | {_pct(o.found, o.ref)} |", f"| лишних | {o.extra} |", "",
              "| ошибка, м | медиана | p90 |", "|---|---|---|",
              f"| центр по x | {_error_cells(o.dx)} |", f"| ширина | {_error_cells(o.dw)} |", "",
              "## По домам", ""]
    return "\n".join(lines + [_house_line(h) for h in houses]) + "\n"


def to_json(houses: list[House]) -> str:
    checked = [h for h in houses if h.diffs]
    body = {"fields": totals(checked), "openings": asdict(_merged(checked)),
            "houses": [asdict(h) for h in houses]}
    return json.dumps(body, ensure_ascii=False, indent=2)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("ref", type=Path, help="папка эталона")
    p.add_argument("got", type=Path, help="папка проверяемых разметок")
    p.add_argument("-o", "--out", type=Path, help="записать отчёт в файл")
    p.add_argument("--json", action="store_true", help="вывести JSON, а не markdown")
    args = p.parse_args()
    houses = compare_dirs(args.ref, args.got, load().data.manual.compare)
    text = to_json(houses) if args.json else render(houses, args.ref, args.got)
    if args.out:
        args.out.write_text(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
