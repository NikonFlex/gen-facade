"""Дом как последовательность токенов для модели шага 4
(`generation: Раскладка — последовательность токенов`).

Последовательность — условие и ответ:

    <house> режим, параметры дома, палитра, виды выводимых элементов
    <side> длина [<entrance>] {<forbidden> x0 x1} {проём плана: вид x w}     — на каждую стену
    <answer>
    <types> n {w h}                                       — типоразмеры окон дома, n ≤ window_types
    <wall> {элемент} {зона}                                                  — на каждую стену
    <end>

    окно:    cls:window x y size:k [<floor> n] [вид cols rows] [материал] [<parent> n] {признак}
             [заданные поля]
    элемент: класс x y w h [<floor> n] [вид cols rows] [материал] [<parent> n] {признак}
             [заданные поля]
    зона:    роль материал число_точек {x y}

Окно ссылается на типоразмер дома (gf#212): его ширина и высота — типоразмера; в «окна из плана»
ширину окна плана потом ставит привязка (snap.py), типоразмер задаёт высоту. Подоконник, наличник,
ставни и козырёк в ответе — не элементы, а признаки проёма (`trim:`): прямоугольники по виду дома
считает код (derive.py) при разборе.

Стены идут по обходу контура от стороны входа — как стороны плана
(спека plan-input, «Сторона», номер).
Числа — целые шаги сетки (config/tokens.toml). Имена элементов в токены не пишутся: родитель —
номер элемента в своей стене. Режимы отличаются условием: в режиме 2 окна плана — в условии
и помечены в ответе как заданные; в режиме 1 их нет в условии, и в ответе они не заданные.
"""

import math
from collections import Counter
from enum import StrEnum
from typing import NamedTuple

from genfacade import derive
from genfacade.config import Config, Tokens
from genfacade.derive import Flags
from genfacade.schema import (
    EPS,
    BuildingType,
    CanopyKind,
    CasingKind,
    Element,
    ElementClass,
    FacadeSheet,
    FixedField,
    HouseSpec,
    MaterialZone,
    Mode,
    OpeningKind,
    OpeningVariant,
    PaletteRole,
    RoofKind,
    ShutterKind,
    Side,
    SideFacade,
    SillKind,
    Trim,
    VariantKind,
    ZoneRole,
)


class Mark(StrEnum):
    """Служебные токены: границы частей и подписи необязательных полей."""

    HOUSE = "<house>"
    SIDE = "<side>"
    ENTRANCE = "<entrance>"
    FORBIDDEN = "<forbidden>"
    ANSWER = "<answer>"
    TYPES = "<types>"
    WALL = "<wall>"
    FLOOR = "<floor>"
    PARENT = "<parent>"
    END = "<end>"


class TokenError(ValueError):
    """Дом не записывается токенами или последовательность не разбирается; текст — причина."""


# Значения разных enum пересекаются («window» — и класс, и вид проёма плана), поэтому токен
# значения — с приставкой своего enum.
ENUMS = {"mode": Mode, "type": BuildingType, "roof": RoofKind, "open": OpeningKind,
         "cls": ElementClass, "var": VariantKind, "mat": PaletteRole, "role": ZoneRole,
         "fix": FixedField, "sill_kind": SillKind, "casing_kind": CasingKind,
         "shutters_kind": ShutterKind, "canopy_kind": CanopyKind, "trim": Trim}
PREFIX = {enum: name for name, enum in ENUMS.items()}
HALF_STEP_UP = 1e-6  # запас на хвост float при округлении полушага; допуск, не настройка
KIND = "kind"    # вид материала из библиотеки — открытый набор из config/library.toml
STYLE = "style"  # стиль дома — открытый набор из config/synthetic.toml
SIZE = "size"    # номер типоразмера окна дома: от 0 до window_types − 1 (config/tokens.toml)


def tok(value: StrEnum) -> str:
    return f"{PREFIX[type(value)]}:{value}"


def vocabulary(cfg: Config) -> list[str]:
    """Все токены в постоянном порядке: номер токена — его место в этом списке."""
    numbers = [str(n) for n in range(units(cfg.tokens.max_m, cfg.tokens) + 1)]
    values = [tok(v) for enum in ENUMS.values() for v in enum]
    kinds = [f"{KIND}:{k}" for k in cfg.library.kinds]
    styles = [f"{STYLE}:{s}" for s in ["", *cfg.synthetic.spec.styles]]
    sizes = [size_tok(k) for k in range(cfg.tokens.window_types)]
    return [*map(str, Mark), *values, *kinds, *styles, *sizes, *numbers]


def size_tok(k: int) -> str:
    return f"{SIZE}:{k}"


def units(metres: float, cfg: Tokens) -> int:
    """Метры → целые шаги сетки. Ровно полшага — всегда вверх: иначе два окна с одним верхом
    на полушаге (2.975 м) расходятся из-за хвостов float."""
    if not 0 <= metres <= cfg.max_m:
        raise TokenError(f"размер {metres} м вне сетки 0…{cfg.max_m} м")
    return math.floor(metres / cfg.grid_m + 0.5 + HALF_STEP_UP)


def metres(n: int, cfg: Tokens) -> float:
    return round(n * cfg.grid_m, 6)


def lines(tokens: list[str]) -> list[str]:
    """Последовательность строками для чтения глазами: часть, стена, элемент, зона — с новой."""
    starts = tuple(f"{PREFIX[enum]}:" for enum in (ElementClass, ZoneRole))
    out: list[list[str]] = []
    for t in tokens:
        if not out or t in (Mark.HOUSE, Mark.SIDE, Mark.ANSWER, Mark.TYPES, Mark.WALL, Mark.END) \
                or t.startswith(starts):
            out.append([])
        out[-1].append(t)
    return [" ".join(row) for row in out]


# ——— запись ———

def encode(sheet: FacadeSheet, mode: Mode, cfg: Config) -> list[str]:
    """Условие и ответ одной последовательностью."""
    return [*condition(sheet, mode, cfg), *answer(sheet, mode, cfg)]


def condition(sheet: FacadeSheet, mode: Mode, cfg: Config) -> list[str]:
    """Что модели дано: режим, параметры дома и стены с тем, что на них задал план."""
    spec, t = sheet.spec, cfg.tokens
    out = [Mark.HOUSE, tok(mode), tok(spec.building_type), str(spec.floors),
           *(str(units(h, t)) for h in spec.floor_heights_m),
           str(units(spec.plinth_m, t)), str(units(spec.eaves_m, t)),
           tok(spec.roof.kind), f"{STYLE}:{spec.style}", *(tok(spec.trim.kind(t)) for t in Trim)]
    for m in spec.materials:
        out += [_material(m.id), f"{KIND}:{m.kind}"]
    for f in sheet.facades:
        out += _side(f.side, mode, t)
    return _known(out, cfg)


def answer(sheet: FacadeSheet, mode: Mode, cfg: Config) -> list[str]:
    """Что модель должна выдать: типоразмеры окон дома, элементы и зоны всех стен подряд.
    Выводимые элементы (подоконник, наличник, ставни, козырёк) — признаками своего проёма."""
    sizes = window_sizes([e for f in sheet.facades for e in f.elements
                          if e.cls is ElementClass.WINDOW], cfg)
    out: list[str] = [Mark.ANSWER, Mark.TYPES, str(len(sizes)),
                      *(str(n) for size in sizes for n in size)]
    for f in sheet.facades:
        out.append(Mark.WALL)
        written = derive.base(f.elements)
        writer = _Writer(mode, cfg.tokens, sizes, {e.id: i for i, e in enumerate(written)})
        marks = derive.flags(f.elements)
        for e in written:
            out += _element(e, marks.get(e.id, set()), sheet, writer)
        for z in f.zones:
            out += _zone(z, cfg.tokens)
    return _known([*out, Mark.END], cfg)


Size = tuple[int, int]  # ширина и высота окна в шагах сетки


class _Writer(NamedTuple):
    """Общее для записи элементов стены: режим, сетка, типоразмеры дома, номера элементов."""

    mode: Mode
    cfg: Tokens
    sizes: list[Size]
    index: dict[str, int]


def window_sizes(windows: list[Element], cfg: Config) -> list[Size]:
    """Типоразмеры окон дома, не больше window_types: разных размеров не больше — они и есть,
    иначе — центры групп: начало — самые частые размеры, окно — к ближнему, центр — медиана
    группы (у реальных домов окна разных размеров, gf#212)."""
    found = Counter(_size(w, cfg.tokens) for w in windows)
    limit = cfg.tokens.window_types
    if len(found) <= limit:
        return sorted(found)
    centres = [size for size, _ in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]
    for _ in range(limit * len(found)):  # сходится за несколько шагов; предел — от зацикливания
        groups: dict[int, list[Size]] = {}
        for size, n in found.items():
            groups.setdefault(nearest(size, centres), []).extend([size] * n)
        moved = [_median(groups[k]) if k in groups else c for k, c in enumerate(centres)]
        if moved == centres:
            break
        centres = moved
    return sorted(set(centres))


def nearest(size: Size, sizes: list[Size]) -> int:
    """Номер ближнего типоразмера: по сумме разниц ширины и высоты, при равенстве — меньший."""
    return min(range(len(sizes)), key=lambda k: (abs(sizes[k][0] - size[0])
                                                 + abs(sizes[k][1] - size[1]), k))


def _median(sizes: list[Size]) -> Size:
    ws, hs = sorted(w for w, _ in sizes), sorted(h for _, h in sizes)
    return ws[len(ws) // 2], hs[len(hs) // 2]


def _size(e: Element, cfg: Tokens) -> Size:
    """Размер в шагах сетки — разность краёв на сетке, как у рамки (`_box`)."""
    _, _, w, h = _box(e, cfg)
    return int(w), int(h)


def _known(tokens: list[str], cfg: Config) -> list[str]:
    """Отказ, если в последовательность попал токен не из словаря (стиль, вид материала)."""
    unknown = sorted(set(tokens) - set(vocabulary(cfg)))
    if unknown:
        raise TokenError(f"нет в словаре: {unknown}")
    return [str(t) for t in tokens]


def _material(material_id: str) -> str:
    try:
        return tok(PaletteRole(material_id))
    except ValueError:
        raise TokenError(f"материал {material_id!r} — не роль палитры") from None


def _side(side: Side, mode: Mode, cfg: Tokens) -> list[str]:
    out = [Mark.SIDE, str(units(side.length_m, cfg))]
    if side.has_entrance:
        out.append(Mark.ENTRANCE)
    for z in side.forbidden:
        out += [Mark.FORBIDDEN, str(units(z.x0_m, cfg)), str(units(z.x1_m, cfg))]
    for o in side.openings:
        if given(o.kind, mode):
            # ширина — разность краёв на сетке, как у элемента в ответе (_box): проём плана не на
            # сетке (окно GenPlan 1,434 м) иначе в условии на шаг шире, чем модель его пишет
            x = units(o.x_m, cfg)
            out += [tok(o.kind), str(x), str(units(o.x_m + o.width_m, cfg) - x)]
    return out


def given(kind: OpeningKind, mode: Mode) -> bool:
    """Проём плана задан модели: вход — всегда, окна — только в режиме 2."""
    return mode is Mode.WITH_OPENINGS or kind is not OpeningKind.WINDOW


def _fixed(e: Element, mode: Mode) -> list[FixedField]:
    """Заданные поля элемента в этом режиме: в режиме 1 окно ставит модель."""
    blind_window = mode is Mode.BLIND and e.cls is ElementClass.WINDOW
    return [] if blind_window else e.fixed


def _element(e: Element, marks: set[Trim], sheet: FacadeSheet, w: _Writer) -> list[str]:
    box = _box(e, w.cfg)
    if e.cls is ElementClass.WINDOW:  # окно — типоразмером дома, а не шириной и высотой
        box = box[:2] + [size_tok(nearest(_size(e, w.cfg), w.sizes))]
    out = [tok(e.cls), *box]
    if e.floor is not None:
        out += [Mark.FLOOR, str(e.floor)]
    if e.variant is not None:
        out += [tok(e.variant.kind), str(e.variant.cols), str(e.variant.rows)]
    if e.material is not None:
        out.append(_material(e.material))
    if e.parent in w.index:  # родитель — выводимый элемент: связь выводит код, не пишется
        out += [Mark.PARENT, str(w.index[e.parent])]
    return out + _trims(e, marks, sheet) + [tok(f) for f in _fixed(e, w.mode)]


def _trims(e: Element, marks: set[Trim], sheet: FacadeSheet) -> list[str]:
    """Признаки выводимых элементов проёма; вида, которого у дома нет, быть не может."""
    for t in marks:
        if not sheet.spec.trim.has(t):
            raise TokenError(f"элемент {e.id}: признак {t}, а вида {t} у дома нет")
    return [tok(t) for t in Trim if t in marks]


def _box(e: Element, cfg: Tokens) -> list[str]:
    """x y w h в шагах сетки. На сетку ставятся края, а размер — разность: иначе верх окон
    одной линии разъезжается на шаг. Тонкая деталь (подоконник) — не тоньше одного шага."""
    x, y = units(e.x_m, cfg), units(e.y_m, cfg)
    w = max(1, units(e.x_m + e.w_m, cfg) - x)
    h = max(1, units(e.y_m + e.h_m, cfg) - y)
    return [str(x), str(y), str(w), str(h)]


def _zone(z: MaterialZone, cfg: Tokens) -> list[str]:
    points = [str(units(v, cfg)) for p in z.shape for v in p]
    return [tok(z.role), _material(z.material), str(len(z.shape)), *points]


# ——— разбор ———

class _Reader:
    """Чтение последовательности слева направо; не то, что ждали, — TokenError."""

    def __init__(self, tokens: list[str], cfg: Tokens):
        self.tokens, self.at, self.cfg = tokens, 0, cfg
        self.sizes: list[Size] = []  # типоразмеры окон из начала ответа

    def peek(self) -> str:
        return self.tokens[self.at] if self.at < len(self.tokens) else ""

    def take(self) -> str:
        if self.at >= len(self.tokens):
            raise TokenError("последовательность оборвалась")
        self.at += 1
        return self.tokens[self.at - 1]

    def expect(self, mark: Mark) -> None:
        got = self.take()
        if got != mark:
            raise TokenError(f"токен {self.at}: ждали {mark}, пришло {got!r}")

    def number(self) -> int:
        got = self.take()
        if not got.isdigit():
            raise TokenError(f"токен {self.at}: ждали число, пришло {got!r}")
        return int(got)

    def length(self) -> float:
        return metres(self.number(), self.cfg)

    def value(self, enum: type[StrEnum]) -> StrEnum | None:
        """Значение enum, если следующий токен — его; иначе None, токен не съеден."""
        name, _, value = self.peek().partition(":")
        if name != PREFIX[enum] or value not in set(enum):
            return None
        self.at += 1
        return enum(value)


def decode(tokens: list[str], walls: FacadeSheet, cfg: Config) -> FacadeSheet:
    """Ответ модели → стены с элементами и зонами; walls — дом после развёртки (шаг 3).
    Выводимые элементы ставит код (derive.py) по признакам проёмов и виду дома."""
    r = _Reader(tokens, cfg.tokens)
    r.expect(Mark.ANSWER)
    r.sizes = _read_sizes(r, cfg.tokens.window_types)
    facades = []
    for f in walls.facades:
        wall, marks = _wall(r, f)
        _check_trims(marks, walls.spec)
        wall = _exact(wall, walls.spec, cfg.tokens)
        ctx = derive.Wall(walls.spec, f.side.length_m, cfg.derive)
        facades.append(wall.model_copy(update={
            "elements": derive.place(wall.elements, marks, ctx)}))
    r.expect(Mark.END)
    if r.at != len(tokens):
        raise TokenError(f"после {Mark.END} ещё {len(tokens) - r.at} токенов")
    return walls.model_copy(update={"facades": facades})


def _read_sizes(r: _Reader, limit: int) -> list[Size]:
    r.expect(Mark.TYPES)
    n = r.number()
    if n > limit:
        raise TokenError(f"токен {r.at}: типоразмеров {n}, а можно не больше {limit}")
    sizes = [(r.number(), r.number()) for _ in range(n)]
    if any(0 in size for size in sizes):
        raise TokenError(f"токен {r.at}: типоразмер окна нулевой — {sizes}")
    return sizes


def _check_trims(marks: Flags, spec: HouseSpec) -> None:
    for owner, trims in marks.items():
        if missing := sorted(t for t in trims if not spec.trim.has(t)):
            raise TokenError(f"элемент {owner}: признаки {missing}, а таких видов у дома нет")


def bare(sheet: FacadeSheet) -> FacadeSheet:
    """Дом после развёртки: стены без элементов и зон — то, что есть до ответа модели."""
    walls = [f.model_copy(update={"elements": [], "zones": []}) for f in sheet.facades]
    return sheet.model_copy(update={"facades": walls})


def given_sides(sheet: FacadeSheet, mode: Mode) -> FacadeSheet:
    """Дом, у сторон которого только проёмы условия этого режима. В глухом режиме окна плана
    заделаны (шаг 2) — валидатор не должен требовать их на фасаде."""
    facades = [f.model_copy(update={"side": f.side.model_copy(update={"openings": [
        o for o in f.side.openings if given(o.kind, mode)]})}) for f in sheet.facades]
    return sheet.model_copy(update={"facades": facades})


def _wall(r: _Reader, wall: SideFacade) -> tuple[SideFacade, Flags]:
    r.expect(Mark.WALL)
    elements: list[Element] = []
    marks: Flags = {}
    while (cls := r.value(ElementClass)) is not None:
        e, trims = _read_element(r, cls, len(elements))
        elements.append(e)
        if trims:
            marks[e.id] = trims
    for e in elements:  # родитель — номер элемента в стене; номера за её пределами — брак
        if e.parent is not None and int(e.parent) >= len(elements):
            raise TokenError(f"элемент {e.id}: родитель {e.parent} — такого номера в стене нет")
    named = [e.model_copy(update={"parent": name(int(e.parent)) if e.parent else None})
             for e in elements]
    zones = []
    while (role := r.value(ZoneRole)) is not None:
        zones.append(_read_zone(r, role))
    return wall.model_copy(update={"elements": named, "zones": zones}), marks


def _exact(wall: SideFacade, spec: HouseSpec, cfg: Tokens) -> SideFacade:
    """Края на сетке — на настоящие размеры. Модель видит стену и отметки, округлённые до шага
    сетки, а у плана GenPlan стороны и высоты не на ней (сторона 4,2254 м — в условии 4,25):
    край элемента или зоны, поставленный ровно на край стены или отметку уровня в сетке,
    становится настоящим краем — иначе карниз на 2,5 см выходит за стену. Остальное не трогается."""
    xs = _grid_to_real([0.0, wall.side.length_m], cfg)
    ys = _grid_to_real([0.0, *spec.floor_levels(), spec.eaves_m], cfg)
    elements = [_exact_box(e, xs, ys) for e in wall.elements]
    zones = [z.model_copy(update={"shape": [(_real(x, xs), _real(y, ys)) for x, y in z.shape]})
             for z in wall.zones]
    return wall.model_copy(update={"elements": elements, "zones": zones})


def _grid_to_real(values: list[float], cfg: Tokens) -> dict[float, float]:
    """Узел сетки → настоящий размер, только если он и правда не на сетке: хвост float
    (5.6000000000000005) — не повод менять узел."""
    grid = {metres(units(v, cfg), cfg): v for v in values}
    return {g: v for g, v in grid.items() if abs(g - v) > EPS}


def _real(value: float, known: dict[float, float]) -> float:
    return next((real for grid, real in known.items() if abs(value - grid) <= EPS), value)


def _exact_box(e: Element, xs: dict[float, float], ys: dict[float, float]) -> Element:
    x0, x1 = _real(e.x_m, xs), _real(e.x_m + e.w_m, xs)
    y0, y1 = _real(e.y_m, ys), _real(e.y_m + e.h_m, ys)
    if (x0, x1, y0, y1) == (e.x_m, e.x_m + e.w_m, e.y_m, e.y_m + e.h_m):
        return e
    return e.model_copy(update={"x_m": x0, "w_m": x1 - x0, "y_m": y0, "h_m": y1 - y0})


def name(index: int) -> str:
    """Имя элемента после разбора — по его месту в стене."""
    return f"e{index}"


def _read_element(r: _Reader, cls: ElementClass, index: int) -> tuple[Element, set[Trim]]:
    data: dict = {"id": name(index), "cls": cls, **_read_box(r, cls)}
    if r.peek() == Mark.FLOOR:
        r.take()
        data["floor"] = r.number()
    if (kind := r.value(VariantKind)) is not None:
        data["variant"] = _build(OpeningVariant, {"kind": kind, "cols": r.number(),
                                                  "rows": r.number()}, r)
    if (material := r.value(PaletteRole)) is not None:
        data["material"] = material
    if r.peek() == Mark.PARENT:
        r.take()
        data["parent"] = str(r.number())  # пока номер; имя — когда прочитана вся стена
    trims = _read_trims(r, cls)
    data["fixed"] = _read_fixed(r)
    return _build(Element, data, r), trims


def _read_box(r: _Reader, cls: ElementClass) -> dict[str, float]:
    """x y w h; у окна ширина и высота — его типоразмера."""
    x, y = r.length(), r.length()
    if cls is not ElementClass.WINDOW:
        return {"x_m": x, "y_m": y, "w_m": r.length(), "h_m": r.length()}
    got = r.take()
    name_, _, k = got.partition(":")
    if name_ != SIZE or not k.isdigit() or int(k) >= len(r.sizes):
        raise TokenError(f"токен {r.at}: ждали типоразмер окна из {len(r.sizes)}, пришло {got!r}")
    w, h = r.sizes[int(k)]
    return {"x_m": x, "y_m": y, "w_m": metres(w, r.cfg), "h_m": metres(h, r.cfg)}


def _read_trims(r: _Reader, cls: ElementClass) -> set[Trim]:
    """Признаки выводимых элементов; признак не своего класса проёма — брак."""
    trims = set()
    while (trim := r.value(Trim)) is not None:
        if derive.OWNER[trim] is not cls:
            raise TokenError(f"токен {r.at}: признак {trim} — у {derive.OWNER[trim]}, а не у {cls}")
        trims.add(trim)
    return trims


def _read_fixed(r: _Reader) -> list[FixedField]:
    fixed = []
    while (field := r.value(FixedField)) is not None:
        fixed.append(field)
    return fixed


def _read_zone(r: _Reader, role: ZoneRole) -> MaterialZone:
    material = r.value(PaletteRole)
    if material is None:
        raise TokenError(f"токен {r.at + 1}: у зоны {role} нет материала")
    shape = [(r.length(), r.length()) for _ in range(r.number())]
    return _build(MaterialZone, {"role": role, "material": material, "shape": shape}, r)


def _build(model: type, data: dict, r: _Reader):
    """Собрать объект схемы; что схема не принимает (ширина 0, вид не того класса) — брак."""
    try:
        return model(**data)
    except ValueError as e:
        raise TokenError(f"токен {r.at}: {e}") from e
