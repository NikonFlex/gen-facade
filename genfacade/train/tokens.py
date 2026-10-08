"""Дом как последовательность токенов для модели шага 4 (specs/generation.md, п. 3).

Последовательность — условие и ответ:

    <house> режим, параметры дома, палитра
    <side> длина [<entrance>] {<forbidden> x0 x1} {проём плана: вид x w}     — на каждую стену
    <answer>
    <wall> {элемент} {зона}                                                  — на каждую стену
    <end>

    элемент: класс x y w h [<floor> n] [вид cols rows] [материал] [<parent> n] [заданные поля]
    зона:    роль материал число_точек {x y}

Стены идут по обходу контура от стороны входа — как стороны плана (plan-input.md, Side.index).
Числа — целые шаги сетки (config/tokens.toml). Имена элементов в токены не пишутся: родитель —
номер элемента в своей стене. Режимы отличаются условием: в режиме 2 окна плана — в условии
и помечены в ответе как заданные; в режиме 1 их нет в условии, и в ответе они не заданные.
"""

import math
from enum import StrEnum

from genfacade.config import Config, Tokens
from genfacade.schema import (
    BuildingType,
    Element,
    ElementClass,
    FacadeSheet,
    FixedField,
    MaterialZone,
    Mode,
    OpeningKind,
    OpeningVariant,
    PaletteRole,
    RoofKind,
    Side,
    SideFacade,
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
         "fix": FixedField}
PREFIX = {enum: name for name, enum in ENUMS.items()}
HALF_STEP_UP = 1e-6  # запас на хвост float при округлении полушага; допуск, не настройка
KIND = "kind"    # вид материала из библиотеки — открытый набор из config/library.toml
STYLE = "style"  # стиль дома — открытый набор из config/synthetic.toml


def tok(value: StrEnum) -> str:
    return f"{PREFIX[type(value)]}:{value}"


def vocabulary(cfg: Config) -> list[str]:
    """Все токены в постоянном порядке: номер токена — его место в этом списке."""
    numbers = [str(n) for n in range(units(cfg.tokens.max_m, cfg.tokens) + 1)]
    values = [tok(v) for enum in ENUMS.values() for v in enum]
    kinds = [f"{KIND}:{k}" for k in cfg.library.kinds]
    styles = [f"{STYLE}:{s}" for s in ["", *cfg.synthetic.spec.styles]]
    return [*map(str, Mark), *values, *kinds, *styles, *numbers]


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
        if not out or t in (Mark.HOUSE, Mark.SIDE, Mark.ANSWER, Mark.WALL, Mark.END) \
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
           tok(spec.roof.kind), f"{STYLE}:{spec.style}"]
    for m in spec.materials:
        out += [_material(m.id), f"{KIND}:{m.kind}"]
    for f in sheet.facades:
        out += _side(f.side, mode, t)
    return _known(out, cfg)


def answer(sheet: FacadeSheet, mode: Mode, cfg: Config) -> list[str]:
    """Что модель должна выдать: элементы и зоны всех стен подряд."""
    out: list[str] = [Mark.ANSWER]
    for f in sheet.facades:
        out.append(Mark.WALL)
        index = {e.id: i for i, e in enumerate(f.elements)}
        for e in f.elements:
            out += _element(e, index, mode, cfg.tokens)
        for z in f.zones:
            out += _zone(z, cfg.tokens)
    return _known([*out, Mark.END], cfg)


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
        if _given(o.kind, mode):
            out += [tok(o.kind), str(units(o.x_m, cfg)), str(units(o.width_m, cfg))]
    return out


def _given(kind: OpeningKind, mode: Mode) -> bool:
    """Проём плана задан модели: вход — всегда, окна — только в режиме 2."""
    return mode is Mode.WITH_OPENINGS or kind is not OpeningKind.WINDOW


def _fixed(e: Element, mode: Mode) -> list[FixedField]:
    """Заданные поля элемента в этом режиме: в режиме 1 окно ставит модель."""
    blind_window = mode is Mode.BLIND and e.cls is ElementClass.WINDOW
    return [] if blind_window else e.fixed


def _element(e: Element, index: dict[str, int], mode: Mode, cfg: Tokens) -> list[str]:
    out = [tok(e.cls), *_box(e, cfg)]
    if e.floor is not None:
        out += [Mark.FLOOR, str(e.floor)]
    if e.variant is not None:
        out += [tok(e.variant.kind), str(e.variant.cols), str(e.variant.rows)]
    if e.material is not None:
        out.append(_material(e.material))
    if e.parent is not None:
        out += [Mark.PARENT, str(index[e.parent])]
    return out + [tok(f) for f in _fixed(e, mode)]


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
    """Ответ модели → стены с элементами и зонами; walls — дом после развёртки (шаг 3)."""
    r = _Reader(tokens, cfg.tokens)
    r.expect(Mark.ANSWER)
    facades = [_wall(r, f) for f in walls.facades]
    r.expect(Mark.END)
    if r.at != len(tokens):
        raise TokenError(f"после {Mark.END} ещё {len(tokens) - r.at} токенов")
    return walls.model_copy(update={"facades": facades})


def _wall(r: _Reader, wall: SideFacade) -> SideFacade:
    r.expect(Mark.WALL)
    elements: list[Element] = []
    while (cls := r.value(ElementClass)) is not None:
        elements.append(_read_element(r, cls, len(elements)))
    for e in elements:  # родитель — номер элемента в стене; номера за её пределами — брак
        if e.parent is not None and int(e.parent) >= len(elements):
            raise TokenError(f"элемент {e.id}: родитель {e.parent} — такого номера в стене нет")
    named = [e.model_copy(update={"parent": name(int(e.parent)) if e.parent else None})
             for e in elements]
    zones = []
    while (role := r.value(ZoneRole)) is not None:
        zones.append(_read_zone(r, role))
    return wall.model_copy(update={"elements": named, "zones": zones})


def name(index: int) -> str:
    """Имя элемента после разбора — по его месту в стене."""
    return f"e{index}"


def _read_element(r: _Reader, cls: ElementClass, index: int) -> Element:
    x, y, w, h = (r.length() for _ in range(4))
    data: dict = {"id": name(index), "cls": cls, "x_m": x, "y_m": y, "w_m": w, "h_m": h}
    if r.peek() == Mark.FLOOR:
        r.take()
        data["floor"] = r.number()
    if (kind := r.value(VariantKind)) is not None:
        data["variant"] = OpeningVariant(kind=kind, cols=r.number(), rows=r.number())
    if (material := r.value(PaletteRole)) is not None:
        data["material"] = material
    if r.peek() == Mark.PARENT:
        r.take()
        data["parent"] = str(r.number())  # пока номер; имя — когда прочитана вся стена
    data["fixed"] = _read_fixed(r)
    return _build(Element, data, r)


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
