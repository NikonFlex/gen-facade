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

Место окну модели страж выбирает в обоих режимах: в «окна из плана» проёмы плана первого этажа —
занятые отрезки, своё окно модель туда не ставит (налезало на широкое окно плана GenPlan, gf#197).

Окно пишется не шириной и высотой, а номером типоразмера дома из начала ответа (`<types>`, gf#212):
страж оставляет типоразмеры, с которыми окно встаёт на свободное место и под карниз, а x — где
помещается самый узкий типоразмер дома. Признаки выводимых элементов (`trim:`) — только у своего
класса проёма и только тех видов, что есть у дома.

В обоих режимах (gf#197): рамка любого элемента — в пределах стены и не выше карниза; проём плана
(в «окна из плана» — окна и двери, в глухом — вход) модель пишет числами условия: очередной
элемент его класса — в x и ширину проёма, на первом этаже, с `fix:x_m fix:w_m`; стену не
закончить, пока проёмы плана не поставлены. Иначе на реальных домах элементы выходили за стену на
метры, а проём плана пропадал или смещался (0 годных из 20, `docs/metrics-results.md`, 25.10).
"""

import math
from bisect import bisect_right
from enum import Enum, auto
from typing import NamedTuple

from genfacade.config import Config, Tokens
from genfacade.derive import OWNER, TRIM_OF
from genfacade.schema import (
    DOOR_KINDS,
    EPS,
    ElementClass,
    FacadeSheet,
    FixedField,
    ForbiddenZone,
    HouseTrim,
    Mode,
    Opening,
    PaletteRole,
    Trim,
    VariantKind,
    ZoneRole,
)
from genfacade.snap import PLAN_CLASS
from genfacade.train import tokens
from genfacade.train.tokens import PREFIX, Mark
from genfacade.validate import OPENINGS  # что не должно пересекаться — как у валидатора

X, Y, W, H = 0, 1, 2, 3  # места чисел рамки x y w h


Span = tuple[int, int]
FIX_ORDER = (FixedField.X, FixedField.W)  # заданные поля проёма плана — в этом порядке (`tokens`)


class Planned(NamedTuple):
    """Проём плана в условии стены: класс его элемента, x и ширина в шагах (`tokens._side`)."""

    cls: ElementClass
    x: int
    w: int


class Wall(NamedTuple):
    """Стена в шагах сетки: длина, занятые условием отрезки [a, b) — на всех этажах (busy) и
    только на первом (ground), — низ каждого этажа выше первого (floors), карниз (height; 0 —
    без предела) и проёмы плана в порядке условия (plan)."""

    length: int
    busy: list[Span]
    ground: list[Span] = []
    floors: tuple[int, ...] = ()
    height: int = 0
    plan: tuple[Planned, ...] = ()

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
        self.zone, self.fixed = (
            {i for i, w in enumerate(words) if w.startswith(f"{PREFIX[enum]}:")}
            for enum in (ZoneRole, FixedField))
        self.material = {i: PaletteRole(w.split(":", 1)[1]) for i, w in enumerate(words)
                         if w.startswith(f"{PREFIX[PaletteRole]}:")}
        self.variant = {i: VariantKind(w.split(":", 1)[1]) for i, w in enumerate(words)
                        if w.startswith(f"{PREFIX[VariantKind]}:")}
        self.fix = {FixedField(w.split(":", 1)[1]): i for i, w in enumerate(words)
                    if w.startswith(f"{PREFIX[FixedField]}:")}
        self.trim = {i: Trim(w.split(":", 1)[1]) for i, w in enumerate(words)
                     if w.startswith(f"{PREFIX[Trim]}:")}
        self.sizes = {i: int(w.split(":", 1)[1]) for i, w in enumerate(words)
                      if w.startswith(f"{tokens.SIZE}:")}  # номер токена → номер типоразмера
        self.types = words.index(Mark.TYPES)
        self.wall, self.end = words.index(Mark.WALL), words.index(Mark.END)
        self.floor, self.parent = words.index(Mark.FLOOR), words.index(Mark.PARENT)
        self.size = len(words)


class Need(Enum):
    """Что ответ обязан написать следующим (`tokens.decode`)."""

    NUMBER = auto()
    POSITIVE = auto()  # ширина, высота, число точек зоны
    MATERIAL = auto()
    POINTS = auto()    # число точек зоны: за ним — по два числа на точку
    TYPES = auto()     # число типоразмеров окон: за ним — по два числа на типоразмер
    SIZE = auto()      # номер типоразмера окна


# Необязательные поля элемента после рамки — в этом порядке (`tokens._element`): этаж, вид,
# материал, родитель, признаки выводимых элементов (`trim:`, в порядке Trim); заданные поля
# (`fix:`) — последними, сколько угодно.
FLOOR_FIELD, VARIANT_FIELD, MATERIAL_FIELD, PARENT_FIELD = range(4)
TRIM_FIELD = {t: PARENT_FIELD + 1 + k for k, t in enumerate(Trim)}
FIXED_FIELD = PARENT_FIELD + 1 + len(Trim)
BOX = [Need.NUMBER, Need.NUMBER, Need.POSITIVE, Need.POSITIVE]
WINDOW_BOX = [Need.NUMBER, Need.NUMBER, Need.SIZE]  # окно — x y и типоразмер дома
# Зона корпуса — прямоугольник: (x0 y0) (x1 y0) (x1 y1) (x0 y1). Правило на каждое число точек:
# «*» — любое на стене, «>» k — больше k-го числа, «=» k — равно k-му.
ZONE_RECT = (("*", 0), ("*", 0), (">", 0), ("=", 1), ("=", 2), (">", 1), ("=", 0), ("=", 5))


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
        self.header = False               # `<types>` написан
        self.sizes: list[tuple[int, int]] = []  # типоразмеры окон дома, ширина и высота в шагах
        self.numbers: list[int] = []      # числа типоразмеров, пока они пишутся

    def step(self, token: int) -> None:
        v = self.vocab
        if self.need:
            self._number(token)
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
        elif token in v.trim:
            self.field = TRIM_FIELD[v.trim[token]]
        else:
            self._part(token)
        self.done = token == v.end

    def _number(self, token: int) -> None:
        """Токен, которого ждали: число или материал; за числом точек и типоразмеров — их числа."""
        v = self.vocab
        need = self.need.pop(0)
        if need is Need.POINTS:
            self.need = [Need.NUMBER] * 2 * v.number.get(token, 0)
        elif need is Need.TYPES:
            self.need = [Need.POSITIVE] * 2 * v.number.get(token, 0)
        elif self.at < 0:
            self._size_number(v.number.get(token, 0))

    def _part(self, token: int) -> None:
        """Начало элемента, зоны, стены или типоразмеров."""
        v = self.vocab
        if token in v.cls:
            self.cls, self.field = v.cls[token], -1
            self.need = list(WINDOW_BOX if self.cls is ElementClass.WINDOW else BOX)
        elif token in v.zone:
            self.field, self.zones, self.need = None, True, [Need.MATERIAL, Need.POINTS]
        elif token == v.wall:
            self.at, self.field, self.zones = self.at + 1, None, False
        elif token == v.types:
            self.header, self.need = True, [Need.TYPES]

    def _size_number(self, n: int) -> None:
        self.numbers.append(n)
        if len(self.numbers) == 2:
            self.sizes.append((self.numbers[0], self.numbers[1]))
            self.numbers = []

    def allowed(self) -> set[int] | None:
        """Годные следующими токены; None — ответ кончился, запрещать нечего."""
        v = self.vocab
        if self.done:
            return None
        if self.need:
            need = self.need[0]
            if need is Need.MATERIAL:
                return set(v.material)
            if need is Need.TYPES:  # типоразмеров — не больше, чем номеров у словаря
                return {i for i, n in v.number.items() if n <= len(v.sizes)}
            if need is Need.SIZE:
                return {i for i, k in v.sizes.items() if k < len(self.sizes)}
            return {i for i, n in v.number.items() if n > 0 or need is Need.NUMBER}
        if self.at < 0:
            return {v.wall} if self.header else {v.types}
        return self._fields() | self._next()

    def _fields(self) -> set[int]:
        """Поля элемента, которые ещё можно написать после уже написанных."""
        if self.field is None:
            return set()
        v, f = self.vocab, self.field
        door = self.cls is ElementClass.DOOR  # виды двери — только у двери (`schema.Element`)
        kinds = {i for i, k in v.variant.items() if (k in DOOR_KINDS) == door}
        # признак — только у своего класса проёма (derive.OWNER)
        trims = [({i}, TRIM_FIELD[t]) for i, t in v.trim.items() if OWNER[t] is self.cls]
        order = [({v.floor}, FLOOR_FIELD), (kinds, VARIANT_FIELD),
                 (v.material, MATERIAL_FIELD), ({v.parent}, PARENT_FIELD), *trims]
        return set(v.fixed).union(*(ids for ids, at in order if f < at))

    def _next(self) -> set[int]:
        """Начало следующего элемента, зоны, стены или конец ответа."""
        v = self.vocab
        last = self.at >= self.walls - 1
        # выводимые классы — не элементы ответа, а признаки проёма (gf#212); окна — если у дома
        # есть типоразмеры
        own = {i for i, c in v.cls.items() if c not in TRIM_OF
               and (c is not ElementClass.WINDOW or self.sizes)}
        return ({v.end} if last else {v.wall}) | set(v.zone) | (set() if self.zones else own)


class House(NamedTuple):
    """Что стражу известно о доме из условия: роли палитры и виды выводимых элементов."""

    palette: set[PaletteRole]
    trim: HouseTrim = HouseTrim()


class WallGeometry:
    """Страж одного ответа: грамматика, рамка в пределах стены, проёмы плана по условию и место
    окна модели на стене."""

    def __init__(self, walls: list[Wall], vocab: Vocab, narrowest: int,
                 house: House | None = None):
        # narrowest — самое узкое окно корпуса в шагах, пока у дома нет типоразмеров; house —
        # материал элемента и зоны только из палитры дома, признаки — только видов, что у дома есть
        # (None — любые)
        self.walls, self.vocab, self.narrowest = walls, vocab, narrowest
        self.foreign = {i for i, r in vocab.material.items() if house is not None
                        and r not in house.palette}
        self.foreign |= {i for i, t in vocab.trim.items() if house is not None
                         and not house.trim.has(t)}
        self.grammar = Grammar(vocab, len(walls))
        self.at = -1                      # номер стены; до первого `<wall>` — ещё не стена
        self.placed: list[tuple[Span, int]] = []  # отрезок проёма и его этаж
        self.pending: list[Planned] = []  # проёмы плана стены, ещё не поставленные
        self.current: Planned | None = None  # элемент, который пишется, — этот проём плана
        self.fixes = 0                    # сколько полей `fix:` у него уже написано
        self.index = -1                   # номер элемента в стене, который пишется
        self.point = -1                   # чисел точек зоны уже написано; −1 — не в точках
        self.corners: list[int] = []      # числа точек зоны, что пишется
        self.cls: ElementClass | None = None
        self.box: list[int] = []

    def step(self, token: int) -> None:
        v = self.vocab
        in_box = self._in_box()
        in_points = (self.grammar.zones and self.grammar.need[:1] == [Need.NUMBER]
                     and self.point >= 0)
        counted = self.grammar.need[:1] == [Need.POINTS]
        self.grammar.step(token)
        self.point = self.point + 1 if in_points else 0 if counted else -1
        if in_points:
            self.corners.append(v.number.get(token, 0))
        elif counted:
            self.corners = []
        if token == v.wall:
            self.at, self.placed, self.cls, self.index = self.at + 1, [], None, -1
            self.pending = list(self.walls[self.at].plan) if self.at < len(self.walls) else []
        elif token in v.cls:
            self.cls, self.box, self.current, self.fixes = v.cls[token], [], None, 0
            self.index += 1
        elif in_box and token in v.number:
            self._number(v.number[token])
        elif in_box and token in v.sizes:
            self._size(v.sizes[token])
        elif token in v.fixed:
            self.fixes += 1
        elif token in v.zone:
            self.cls = None

    def _number(self, n: int) -> None:
        self.box.append(n)
        if len(self.box) == X + 1 and (head := self._head()) is not None and n == head.x:
            self.current = head
            self.pending.remove(head)
        if len(self.box) == W + 1 and self.cls in OPENINGS:
            floor = self.walls[self.at].floor(self.box[Y])
            self.placed.append(((self.box[X], self.box[X] + self.box[W]), floor))

    def _size(self, k: int) -> None:
        """Типоразмер окна: отрезок окна на этаже занят; у окна плана ширина — плана."""
        sizes = self.grammar.sizes
        w = self.current.w if self.current is not None else sizes[k][0] if k < len(sizes) else 0
        floor = self.walls[self.at].floor(self.box[Y])
        self.placed.append(((self.box[X], self.box[X] + w), floor))
        self.box.append(k)  # рамка окна закончена: x y и типоразмер

    def _in_box(self) -> bool:
        size = len(WINDOW_BOX if self.cls is ElementClass.WINDOW else BOX)
        return (self.cls is not None and len(self.box) < size and bool(self.grammar.need)
                and 0 <= self.at < len(self.walls))

    def _head(self) -> Planned | None:
        """Очередной непоставленный проём плана класса того элемента, что пишется."""
        return next((p for p in self.pending if p.cls is self.cls), None)

    def banned(self) -> list[int]:
        """Номера токенов, запрещённых следующим: всё, чего не ждёт грамматика ответа. В рамке —
        ещё и числа, при которых элемент выходит за стену или карниз, проём плана — не по
        условию, окно в глухом режиме не встаёт на стену; годных нет — только грамматика, брак
        поймает валидатор. После рамки проёма плана — его поля `fix:`; стена не кончается, пока
        её проёмы плана не поставлены."""
        keep = self.grammar.allowed()
        if keep is None:
            return []
        if self._in_box() and self.grammar.need[:1] == [Need.SIZE]:
            keep &= self._sizes() or keep  # годного типоразмера нет — грамматика, брак — валидатору
        elif self._in_box():
            if numbers := self._box_numbers():
                keep = {self.vocab.token[n] for n in numbers}
        elif self.point >= 0 and self.grammar.need and 0 <= self.at < len(self.walls):
            keep &= self._point_numbers()
        elif self.grammar.need[:1] == [Need.POINTS]:
            keep &= {self.vocab.token[len(ZONE_RECT) // 2]}  # зона — прямоугольник, 4 точки
        elif self.grammar.need[:1] == [Need.TYPES] and self._plan_windows():
            # окна плана ставятся типоразмером дома: без типоразмеров окно плана не поставить,
            # и стена с ним не кончается (необученная модель писала «<types> 0», gf#212)
            keep -= {self.vocab.token[0]}
        elif self.grammar.need[:1] == [Need.POSITIVE] and self.at < 0:
            keep &= self._size_numbers()
        else:
            # материал не из палитры дома лист не примет (у реального дома палитра — main, gf#197)
            keep = (self._tail(keep) - self.foreign) or keep  # годного нет — грамматика
        keep = keep or self.grammar.allowed()  # всё запрещено — сэмплеру не из чего выбрать
        return [i for i in range(self.vocab.size) if i not in keep]

    def _sizes(self) -> set[int]:
        """Типоразмеры, с которыми окно не выше карниза, а окно модели ещё и на стене и на
        свободном месте своего этажа."""
        wall, (x, y) = self.walls[self.at], self.box
        busy = wall.taken(wall.floor(y), self.placed)
        out = set()
        for i, k in self.vocab.sizes.items():
            if k >= len(self.grammar.sizes):
                continue
            w, h = self.grammar.sizes[k]
            fits = self.current is not None or (x + w <= wall.length and _free(x, w, busy))
            if fits and (not wall.height or y + h <= wall.height):
                out.add(i)
        return out

    def _size_numbers(self) -> set[int]:
        """Ширина типоразмера — не длиннее самой длинной стены, высота — не выше карниза: окно
        13,9 × 16 м необученной модели не встаёт ни на одну стену (gf#212)."""
        width = len(self.grammar.numbers) % 2 == 0
        top = max(w.length if width else w.height for w in self.walls) if self.walls else 0
        return {i for n, i in self.vocab.token.items() if 0 < n and (not top or n <= top)}

    def _plan_windows(self) -> bool:
        return any(p.cls is ElementClass.WINDOW for w in self.walls for p in w.plan)

    def _box_numbers(self) -> set[int]:
        wall, place = self.walls[self.at], len(self.box)
        allowed = self._bounds(wall, place)
        if (plan := self._plan(wall, place)) is not None:
            allowed &= plan
        planned = self.current is not None or (place == X and self._head() is not None)
        if self.cls is ElementClass.WINDOW and not planned and (geometry := self._allowed()):
            allowed &= set(geometry)  # окно модели — на свободное место: проём плана уже занят
        return allowed

    def _bounds(self, wall: Wall, place: int) -> set[int]:
        """Рамка в пределах стены по длине и, если карниз известен, по высоте."""
        numbers = self.vocab.token
        if place in (X, W):
            start = 0 if place == X else self.box[X]
            return {n for n in numbers if (n > 0 or place == X) and start + n <= wall.length
                    and (place == W or n < wall.length)}
        start = 0 if place == Y else self.box[Y]
        return {n for n in numbers if (n > 0 or place == Y) and (not wall.height or (
            start + n <= wall.height and (place == H or n < wall.height)))}

    def _plan(self, wall: Wall, place: int) -> set[int] | None:
        """Числа проёма плана: x — очередного проёма класса, y — первый этаж, w — его ширина."""
        if place == X:
            head = self._head()
            return None if head is None else {head.x}
        if self.current is None or place == H:
            return None
        if place == W:
            return {self.current.w}
        return {n for n in self.vocab.token if n < wall.floors[0]} if wall.floors else None

    def _point_numbers(self) -> set[int]:
        """Точка зоны — на стене (x до длины, y до карниза) и угол прямоугольника, как все зоны
        корпуса: зоны модели торчали за стену треугольниками на метры (реальные дома, gf#197)."""
        wall, v = self.walls[self.at], self.vocab
        top = wall.length if self.point % 2 == 0 else wall.height or max(v.token)
        if self.point >= len(ZONE_RECT):
            return {i for n, i in v.token.items() if n <= top}
        rule, c = ZONE_RECT[self.point], self.corners
        if rule[0] == "=":
            return {v.token[c[rule[1]]]}
        if rule[0] == "*":  # левый нижний угол — не на краю: правее и выше нужно место
            return {i for n, i in v.token.items() if n < top}
        return {i for n, i in v.token.items() if c[rule[1]] < n <= top}

    def _field_numbers(self) -> set[int]:
        """Этаж — из этажей дома (у проёма плана — первый); родитель — уже написанный элемент
        стены: иначе «родитель 28 — такого номера в стене нет» (реальный дом, gf#197)."""
        v = self.vocab
        if self.grammar.field == PARENT_FIELD:
            return {v.token[n] for n in range(max(self.index, 0)) if n in v.token}
        top = 1 if self.current is not None else len(self.walls[self.at].floors) + 1
        return {v.token[n] for n in range(1, top + 1) if n in v.token}

    def _tail(self, keep: set[int]) -> set[int]:
        """После рамки: поля `fix:` — только у проёма плана и все по порядку; пока на стене есть
        непоставленные проёмы плана, следующий элемент — один из них, стена не кончается."""
        v = self.vocab
        if self.grammar.need and self.grammar.field in (FLOOR_FIELD, PARENT_FIELD):
            return keep & self._field_numbers()
        if self.current is not None and self.grammar.field == -1:
            return {v.floor}  # проём плана — на первом этаже (валидатор ищет его там)
        if self.grammar.field is not None and not self.grammar.need:
            keep = keep - set(v.fixed) - ({v.parent} if self.index <= 0 else set())
            if self.current is not None and self.fixes < len(FIX_ORDER):
                keep = (keep - set(v.cls) - set(v.zone) - {v.wall, v.end}) | {
                    v.fix[FIX_ORDER[self.fixes]]}
        if self.pending:  # иначе модель обходит проём плана подоконниками и карнизами до конца окна
            classes = {p.cls for p in self.pending}
            keep = {i for i in keep if i not in v.cls or v.cls[i] in classes} - set(v.zone) - {
                v.wall, v.end}
        return keep

    def _allowed(self) -> list[int]:
        """Годные числа рамки окна по занятым отрезкам стены; высоту — пусто: её держат грамматика
        и предел карниза."""
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
            return [n for n in numbers if n + self._narrowest() <= wall.length and self._fits(n)]
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
                if _free(x, self._narrowest(), wall.taken(f, self.placed))}

    def _narrowest(self) -> int:
        """Самый узкий типоразмер дома; пока их нет — самое узкое окно корпуса."""
        return min((w for w, _ in self.grammar.sizes), default=self.narrowest)


def _free(x: int, w: int, busy: list[Span]) -> bool:
    return not any(x < b and x + w > a for a, b in busy)


def walls(bare: FacadeSheet, mode: Mode, cfg: Config) -> list[Wall]:
    """Стены дома в шагах сетки — как их видит модель в условии (`tokens.condition`)."""
    t = cfg.tokens
    floors = tuple(tokens.units(y, t) for y in bare.spec.floor_levels()[1:-1])
    height = tokens.units(bare.spec.eaves_m, t)
    out = []
    for f in bare.facades:
        zones = [_outward(z, cfg) for z in f.side.forbidden]
        plan = tuple(_planned(o, t) for o in f.side.openings if tokens.given(o.kind, mode))
        given = [(p.x, p.x + p.w) for p in plan]
        # зоны и проёмы плана — первого этажа: у верхних плана нет
        out.append(Wall(tokens.units(f.side.length_m, t), [], zones + given, floors, height, plan))
    return out


def _planned(o: Opening, t: Tokens) -> Planned:
    """Проём плана теми же числами, что в условии (`tokens._side`)."""
    x = tokens.units(o.x_m, t)
    return Planned(PLAN_CLASS[o.kind], x, tokens.units(o.x_m + o.width_m, t) - x)


def _outward(zone: ForbiddenZone, cfg: Config) -> Span:
    """Зона на сетке — наружу, до узлов, которые её покрывают с допуском валидатора. Округление к
    ближнему узлу ужимало зону 1,930–2,006 м до 1,95–2,00 м: окно, кончающееся на 1,95, страж
    пропускал, а валидатор браковал — заход 2 см (план GenPlan, gf#155)."""
    grid, eps = cfg.tokens.grid_m, cfg.checks.eps_m
    return (math.floor((zone.x0_m + eps) / grid + EPS), math.ceil((zone.x1_m - eps) / grid - EPS))


def guard(bare: FacadeSheet, mode: Mode, vocab: Vocab, cfg: Config) -> WallGeometry | None:
    """Страж для ответа на этот дом в любом режиме: режимы различаются проёмами плана в условии.
    Включён ли запрет в конвейере — решает вызывающий (config/models.toml, `constrain`)."""
    mix = cfg.synthetic.sizes  # самое узкое окно — профилей, что в корпусе
    used = [mix.genplan] + ([mix.real] if mix.real_share > 0 else [])
    narrowest = tokens.units(min(p.window_width_m[0] for p in used), cfg.tokens)
    palette = {PaletteRole(m.id) for m in bare.spec.materials if m.id in set(PaletteRole)}
    return WallGeometry(walls(bare, mode, cfg), vocab, narrowest, House(palette, bare.spec.trim))
