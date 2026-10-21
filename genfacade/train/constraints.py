"""Запрет при генерации (gf#132): окно модели не заходит в запретную зону стены, на вход, на уже
поставленные проёмы и за край стены (`generation: Окна вне запретных зон`).

Окно пишется токенами `cls:window x y w h …` (train/tokens.py), числа — шаги сетки. Страж читает
ответ по токену и, когда модель пишет x или w окна, оставляет ей только числа, дающие годное
окно: остальным токенам сэмплер ставит логиты −∞. Занятые отрезки стены — запретные зоны и проёмы
условия (вход) на первом этаже — у верхних этажей плана нет (`evaluation: Запретные зоны — по плану
этажа`) — и проёмы, уже поставленные моделью на этом этаже стены.

Этаж модель пишет после рамки, поэтому он берётся из y — второго числа рамки, до w: x годен, если
окно помещается хотя бы на одном этаже, w — по занятым отрезкам этажа, куда попал y
(`docs/decisions.md`, 21.10). Окно второго этажа над окном первого не запрещено.

Только глухой режим: в «окна из плана» окна — проёмы плана, место и ширину им ставит шаг 5.
"""

import math
from bisect import bisect_right
from typing import NamedTuple

from genfacade.config import Config
from genfacade.schema import EPS, ElementClass, FacadeSheet, ForbiddenZone, Mode, ZoneRole
from genfacade.train import tokens
from genfacade.train.tokens import PREFIX, Mark
from genfacade.validate import OPENINGS  # что не должно пересекаться — как у валидатора

X, Y, W = 0, 1, 2  # места x, y и w среди чисел рамки x y w h


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
    """Номера служебных токенов словаря: числа, классы, начало зоны, начало стены."""

    def __init__(self, words: list[str]):
        self.number = {i: int(w) for i, w in enumerate(words) if w.isdigit()}
        self.token = {n: i for i, n in self.number.items()}
        cls, role = PREFIX[ElementClass], PREFIX[ZoneRole]
        self.cls = {i: ElementClass(w.split(":", 1)[1]) for i, w in enumerate(words)
                    if w.startswith(f"{cls}:")}
        self.zone = {i for i, w in enumerate(words) if w.startswith(f"{role}:")}
        self.wall = words.index(Mark.WALL)
        self.size = len(words)


class WallGeometry:
    """Страж одного ответа: что модель уже написала и какие числа сейчас запрещены."""

    def __init__(self, walls: list[Wall], vocab: Vocab, narrowest: int):
        # narrowest — самое узкое окно корпуса в шагах: x, за которым оно не помещается, не годен
        self.walls, self.vocab, self.narrowest = walls, vocab, narrowest
        self.at = -1                      # номер стены; до первого `<wall>` — ещё не стена
        self.placed: list[tuple[Span, int]] = []  # отрезок проёма и его этаж
        self.cls: ElementClass | None = None
        self.box: list[int] = []
        self.closed = False               # рамка x y w h только что дописана

    def step(self, token: int) -> None:
        v = self.vocab
        self.closed = False
        if token == v.wall:
            self.at, self.placed, self.cls = self.at + 1, [], None
        elif token in v.cls:
            self.cls, self.box = v.cls[token], []
        elif token in v.zone:
            self.cls = None
        elif self.cls is not None and token in v.number and len(self.box) < 4:
            self.box.append(v.number[token])
            self.closed = len(self.box) == 4
            if len(self.box) == W + 1 and self.cls in OPENINGS and 0 <= self.at < len(self.walls):
                floor = self.walls[self.at].floor(self.box[Y])
                self.placed.append(((self.box[X], self.box[X] + self.box[W]), floor))

    def banned(self) -> list[int]:
        """Номера токенов, запрещённых следующим. Внутри рамки x y w h любого элемента — только
        числа, ширина и высота больше нуля: иначе после непривычного x или w модель пишет на
        месте числа другой токен, и ответ ломается («ждали число») — gf#132, run 38637413314.
        У окна x и w ещё и годные по стене. Годных нет — не запрещаем ничего, брак поймает
        валидатор. Сразу после рамки — не число: урезанная стражем ширина сбивает модель, и она
        дописывает задуманные ширину и высоту лишними числами (gf#177: «12 32 10 36 50»)."""
        if self.closed:
            return list(self.vocab.number)
        if self.cls is None or len(self.box) >= 4 or not 0 <= self.at < len(self.walls):
            return []
        allowed = self._allowed()
        if not allowed:
            return []
        keep = {self.vocab.token[n] for n in allowed}
        return [i for i in range(self.vocab.size) if i not in keep]

    def _allowed(self) -> list[int]:
        numbers = list(self.vocab.token)
        place = len(self.box)
        if self.cls is not ElementClass.WINDOW or place not in (X, W):
            return [n for n in numbers if n > 0 or place in (X, Y)]
        wall = self.walls[self.at]
        if place == X:
            # Окну нужно место: x, за которым до края или занятого отрезка уже самого узкого окна,
            # загоняет модель в ширину, какой она не видела, — и ответ ломается (gf#153: x 98 на
            # стене 109 шагов, ширина 4, дальше «ждали <wall>, пришло '32'»). Этажа ещё нет —
            # годен x, при котором окно помещается хотя бы на одном.
            spans = [wall.taken(f, self.placed) for f in range(1, len(wall.floors) + 2)]
            return [n for n in numbers if n + self.narrowest <= wall.length
                    and any(_free(n, self.narrowest, busy) for busy in spans)]
        x, busy = self.box[X], wall.taken(wall.floor(self.box[Y]), self.placed)
        return [n for n in numbers if 0 < n and x + n <= wall.length and _free(x, n, busy)]


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
    """Страж для ответа на этот дом; в режиме «окна из плана» — None, запрещать нечего.
    Включён ли запрет в конвейере — решает вызывающий (config/models.toml, `constrain`)."""
    if mode is not Mode.BLIND:
        return None
    narrowest = tokens.units(min(cfg.synthetic.openings.window_widths_m), cfg.tokens)
    return WallGeometry(walls(bare, mode, cfg), vocab, narrowest)
