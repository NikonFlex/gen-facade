"""Запрет при генерации (gf#132): окно модели не заходит в запретную зону стены, на вход, на уже
поставленные проёмы и за край стены (`generation: Окна вне запретных зон`).

Окно пишется токенами `cls:window x y w h …` (train/tokens.py), числа — шаги сетки. Страж читает
ответ по токену и, когда модель пишет x или w окна, оставляет ей только числа, дающие годное
окно: остальным токенам сэмплер ставит логиты −∞. Занятые отрезки стены — запретные зоны и проёмы
условия (вход) на первом этаже — у верхних этажей плана нет (`evaluation: Запретные зоны — по плану
этажа`) — и проёмы, уже поставленные моделью на этом этаже стены.

Этаж модель пишет после рамки, поэтому он берётся из y — второго числа рамки, до w: x годен, если
окно помещается хотя бы на одном этаже, y — только на этаже, где x годен, w — по занятым отрезкам
этажа, куда попал y (`docs/decisions.md`, 21.10). Окно второго этажа над окном первого не запрещено.

Место окну — только в глухом режиме: в «окна из плана» окна — проёмы плана, место и ширину им
ставит шаг 5. Формат рамки x y w h страж держит в обоих режимах.
"""

import math
from bisect import bisect_right
from enum import Enum, auto
from typing import NamedTuple

from genfacade.config import Config
from genfacade.schema import (
    DOOR_KINDS,
    EPS,
    ElementClass,
    FacadeSheet,
    FixedField,
    ForbiddenZone,
    Mode,
    PaletteRole,
    VariantKind,
    ZoneRole,
)
from genfacade.train import tokens
from genfacade.train.tokens import PREFIX, Mark
from genfacade.validate import OPENINGS  # что не должно пересекаться — как у валидатора

X, Y, W, H = 0, 1, 2, 3  # места чисел рамки x y w h


Span = tuple[int, int]


class Wall(NamedTuple):
    """Стена в шагах сетки: длина, занятые условием отрезки [a, b) — на всех этажах (busy) и
    только на первом (ground), — и низ каждого этажа выше первого (floors)."""

    length: int
    busy: list[Span]
    ground: list[Span] = []
    floors: tuple[int, ...] = ()

    def floor(self, y: int) -> int:
        """Этаж по высоте низа элемента: 1 — ниже низа второго этажа (и цоколь тоже)."""
        return 1 + bisect_right(self.floors, y)

    def taken(self, floor: int, placed: list[tuple[Span, int]]) -> list[Span]:
        """Занятое на этаже: условие и проёмы, уже поставленные моделью на этом этаже."""
        own = [span for span, at in placed if at == floor]
        return self.busy + (self.ground if floor == 1 else []) + own


class Vocab:
    """Номера токенов словаря по их месту в грамматике ответа: числа, классы элементов, роли
    зон, поля элемента и служебные токены."""

    def __init__(self, words: list[str]):
        self.number = {i: int(w) for i, w in enumerate(words) if w.isdigit()}
        self.token = {n: i for i, n in self.number.items()}
        self.cls = {i: ElementClass(w.split(":", 1)[1]) for i, w in enumerate(words)
                    if w.startswith(f"{PREFIX[ElementClass]}:")}
        self.zone, self.material, self.fixed = (
            {i for i, w in enumerate(words) if w.startswith(f"{PREFIX[enum]}:")}
            for enum in (ZoneRole, PaletteRole, FixedField))
        self.variant = {i: VariantKind(w.split(":", 1)[1]) for i, w in enumerate(words)
                        if w.startswith(f"{PREFIX[VariantKind]}:")}
        self.wall, self.end = words.index(Mark.WALL), words.index(Mark.END)
        self.floor, self.parent = words.index(Mark.FLOOR), words.index(Mark.PARENT)
        self.size = len(words)


class Need(Enum):
    """Что ответ обязан написать следующим (`tokens.decode`)."""

    NUMBER = auto()
    POSITIVE = auto()  # ширина, высота, число точек зоны
    MATERIAL = auto()
    POINTS = auto()    # число точек зоны: за ним — по два числа на точку


# Необязательные поля элемента после рамки — в этом порядке (`tokens._element`); заданные
# поля (`fix:`) — последними, сколько угодно.
FLOOR_FIELD, VARIANT_FIELD, MATERIAL_FIELD, PARENT_FIELD, FIXED_FIELD = range(5)
BOX = [Need.NUMBER, Need.NUMBER, Need.POSITIVE, Need.POSITIVE]


class Grammar:
    """Грамматика ответа: какие токены годны следующими, чтобы `tokens.decode` его разобрал.
    Без неё модель, сбитая непривычным местом, пишет токен условия (`<house>`, `kind:`), поле
    элемента не по порядку или лишнее число точки зоны — и ответ не разбирается (gf#177)."""

    def __init__(self, vocab: Vocab, walls: int):
        self.vocab, self.walls = vocab, walls
        self.at = -1                      # номер стены
        self.need: list[Need] = []
        self.cls: ElementClass | None = None
        self.field: int | None = None     # последнее поле элемента; None — не в элементе
        self.zones = False                # зоны стены начались — элементов больше нет
        self.done = False

    def step(self, token: int) -> None:
        v = self.vocab
        if self.need:
            if self.need.pop(0) is Need.POINTS:
                self.need = [Need.NUMBER] * 2 * v.number.get(token, 0)
            return
        fields = {v.floor: (FLOOR_FIELD, [Need.NUMBER]), v.parent: (PARENT_FIELD, [Need.NUMBER])}
        if token in fields:
            self.field, self.need = fields[token][0], list(fields[token][1])
        elif token in v.variant:
            self.field, self.need = VARIANT_FIELD, [Need.POSITIVE, Need.POSITIVE]
        elif token in v.material:
            self.field = MATERIAL_FIELD
        elif token in v.fixed:
            self.field = FIXED_FIELD
        elif token in v.cls:
            self.cls, self.field, self.need = v.cls[token], -1, list(BOX)
        elif token in v.zone:
            self.field, self.zones, self.need = None, True, [Need.MATERIAL, Need.POINTS]
        elif token == v.wall:
            self.at, self.field, self.zones = self.at + 1, None, False
        self.done = token == v.end

    def allowed(self) -> set[int] | None:
        """Годные следующими токены; None — ответ кончился, запрещать нечего."""
        v = self.vocab
        if self.done:
            return None
        if self.need:
            need = self.need[0]
            if need is Need.MATERIAL:
                return set(v.material)
            return {i for i, n in v.number.items() if n > 0 or need is Need.NUMBER}
        if self.at < 0:
            return {v.wall}
        return self._fields() | self._next()

    def _fields(self) -> set[int]:
        """Поля элемента, которые ещё можно написать после уже написанных."""
        if self.field is None:
            return set()
        v, f = self.vocab, self.field
        door = self.cls is ElementClass.DOOR  # виды двери — только у двери (`schema.Element`)
        kinds = {i for i, k in v.variant.items() if (k in DOOR_KINDS) == door}
        order = [({v.floor}, FLOOR_FIELD), (kinds, VARIANT_FIELD),
                 (v.material, MATERIAL_FIELD), ({v.parent}, PARENT_FIELD)]
        return set(v.fixed).union(*(ids for ids, at in order if f < at))

    def _next(self) -> set[int]:
        """Начало следующего элемента, зоны, стены или конец ответа."""
        v = self.vocab
        last = self.at >= self.walls - 1
        return ({v.end} if last else {v.wall}) | set(v.zone) | (set() if self.zones else set(v.cls))


class WallGeometry:
    """Страж одного ответа: грамматика ответа и, в глухом режиме, место окна на стене."""

    def __init__(self, walls: list[Wall], vocab: Vocab, narrowest: int, places: bool = True):
        # narrowest — самое узкое окно корпуса в шагах: x, за которым оно не помещается, не годен;
        # places — страж выбирает окну место (глухой режим), иначе только грамматика
        self.walls, self.vocab, self.narrowest = walls, vocab, narrowest
        self.places = places
        self.grammar = Grammar(vocab, len(walls))
        self.at = -1                      # номер стены; до первого `<wall>` — ещё не стена
        self.placed: list[tuple[Span, int]] = []  # отрезок проёма и его этаж
        self.cls: ElementClass | None = None
        self.box: list[int] = []

    def step(self, token: int) -> None:
        v = self.vocab
        in_box = bool(self.grammar.need) and self.cls is not None and len(self.box) < 4
        self.grammar.step(token)
        if token == v.wall:
            self.at, self.placed, self.cls = self.at + 1, [], None
        elif token in v.cls:
            self.cls, self.box = v.cls[token], []
        elif in_box and token in v.number:
            self.box.append(v.number[token])
            if len(self.box) == W + 1 and self.cls in OPENINGS and 0 <= self.at < len(self.walls):
                floor = self.walls[self.at].floor(self.box[Y])
                self.placed.append(((self.box[X], self.box[X] + self.box[W]), floor))
        elif token in v.zone:
            self.cls = None

    def banned(self) -> list[int]:
        """Номера токенов, запрещённых следующим: всё, чего не ждёт грамматика ответа. Внутри
        рамки x y w h окна в глухом режиме — ещё и x и w, при которых окно не встаёт на стену;
        годных нет — только грамматика, брак поймает валидатор."""
        keep = self.grammar.allowed()
        if keep is None:
            return []
        if self.places and self.cls is ElementClass.WINDOW and len(self.box) < 4 \
                and 0 <= self.at < len(self.walls) and (allowed := self._allowed()):
            keep = {self.vocab.token[n] for n in allowed}
        return [i for i in range(self.vocab.size) if i not in keep]

    def _allowed(self) -> list[int]:
        """Годные числа рамки окна по стене; высоту — пусто: её держит грамматика."""
        numbers = list(self.vocab.token)
        place = len(self.box)
        if place == H:
            return []
        wall = self.walls[self.at]
        if place == X:
            # Окну нужно место: x, за которым до края или занятого отрезка уже самого узкого окна,
            # загоняет модель в ширину, какой она не видела, — и ответ ломается (gf#153: x 98 на
            # стене 109 шагов, ширина 4, дальше «ждали <wall>, пришло '32'»). Этажа ещё нет —
            # годен x, при котором окно помещается хотя бы на одном.
            return [n for n in numbers if n + self.narrowest <= wall.length and self._fits(n)]
        if place == Y:
            # x годен не на всех этажах — y только там, где годен: иначе у окна первого этажа
            # в запретной зоне нет годной ширины (план GenPlan, 9 из 20 браков, gf#155).
            fits = self._fits(self.box[X])
            return [n for n in numbers if wall.floor(n) in fits] if len(fits) <= len(
                wall.floors) else numbers
        x, busy = self.box[X], wall.taken(wall.floor(self.box[Y]), self.placed)
        return [n for n in numbers if 0 < n and x + n <= wall.length and _free(x, n, busy)]

    def _fits(self, x: int) -> set[int]:
        """Этажи, где на x помещается самое узкое окно."""
        wall = self.walls[self.at]
        return {f for f in range(1, len(wall.floors) + 2)
                if _free(x, self.narrowest, wall.taken(f, self.placed))}


def _free(x: int, w: int, busy: list[Span]) -> bool:
    return not any(x < b and x + w > a for a, b in busy)


def walls(bare: FacadeSheet, mode: Mode, cfg: Config) -> list[Wall]:
    """Стены дома в шагах сетки — как их видит модель в условии (`tokens.condition`)."""
    t = cfg.tokens
    floors = tuple(tokens.units(y, t) for y in bare.spec.floor_levels()[1:-1])
    out = []
    for f in bare.facades:
        zones = [_outward(z, cfg) for z in f.side.forbidden]
        given = [(tokens.units(o.x_m, t), tokens.units(o.x_m + o.width_m, t))
                 for o in f.side.openings if tokens.given(o.kind, mode)]
        # зоны и проёмы плана — первого этажа: у верхних плана нет
        out.append(Wall(tokens.units(f.side.length_m, t), [], zones + given, floors))
    return out


def _outward(zone: ForbiddenZone, cfg: Config) -> Span:
    """Зона на сетке — наружу, до узлов, которые её покрывают с допуском валидатора. Округление к
    ближнему узлу ужимало зону 1,930–2,006 м до 1,95–2,00 м: окно, кончающееся на 1,95, страж
    пропускал, а валидатор браковал — заход 2 см (план GenPlan, gf#155)."""
    grid, eps = cfg.tokens.grid_m, cfg.checks.eps_m
    return (math.floor((zone.x0_m + eps) / grid + EPS), math.ceil((zone.x1_m - eps) / grid - EPS))


def guard(bare: FacadeSheet, mode: Mode, vocab: Vocab, cfg: Config) -> WallGeometry | None:
    """Страж для ответа на этот дом. В «окна из плана» — только формат рамки: у двери GenPlan в
    0,519 м от угла модель пропускала число рамки («ждали число, пришло <floor>», gf#177).
    Включён ли запрет в конвейере — решает вызывающий (config/models.toml, `constrain`)."""
    mix = cfg.synthetic.sizes  # самое узкое окно — профилей, что в корпусе
    used = [mix.genplan] + ([mix.real] if mix.real_share > 0 else [])
    narrowest = tokens.units(min(p.window_width_m[0] for p in used), cfg.tokens)
    return WallGeometry(walls(bare, mode, cfg), vocab, narrowest, mode is Mode.BLIND)
