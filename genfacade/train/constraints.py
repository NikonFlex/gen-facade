"""Запрет при генерации (gf#132): окно модели не заходит в запретную зону стены, на вход, на уже
поставленные проёмы и за край стены (`generation: Окна вне запретных зон`).

Окно пишется токенами `cls:window x y w h …` (train/tokens.py), числа — шаги сетки. Страж читает
ответ по токену и, когда модель пишет x или w окна, называет числа, дающие такое окно: сэмплер
ставит им логиты −∞. Занятые отрезки стены — запретные зоны и проёмы условия плюс проёмы, уже
поставленные моделью на этой стене.

Только глухой режим: в «окна из плана» окна — проёмы плана, место и ширину им ставит шаг 5.
Только по горизонтали: этаж модель пишет после размеров — верно, пока дом одноэтажный.
"""

from typing import NamedTuple

from genfacade.config import Config
from genfacade.schema import ElementClass, FacadeSheet, Mode, ZoneRole
from genfacade.train import tokens
from genfacade.train.tokens import PREFIX, Mark
from genfacade.validate import OPENINGS  # что не должно пересекаться — как у валидатора

X, W = 0, 2  # места x и w среди чисел рамки x y w h


class Wall(NamedTuple):
    """Стена в шагах сетки: длина и занятые условием отрезки [a, b)."""

    length: int
    busy: list[tuple[int, int]]


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


class WallGeometry:
    """Страж одного ответа: что модель уже написала и какие числа сейчас запрещены."""

    def __init__(self, walls: list[Wall], vocab: Vocab):
        self.walls, self.vocab = walls, vocab
        self.at = -1                      # номер стены; до первого `<wall>` — ещё не стена
        self.placed: list[tuple[int, int]] = []
        self.cls: ElementClass | None = None
        self.box: list[int] = []

    def step(self, token: int) -> None:
        v = self.vocab
        if token == v.wall:
            self.at, self.placed, self.cls = self.at + 1, [], None
        elif token in v.cls:
            self.cls, self.box = v.cls[token], []
        elif token in v.zone:
            self.cls = None
        elif self.cls is not None and token in v.number and len(self.box) < 4:
            self.box.append(v.number[token])
            if len(self.box) == W + 1 and self.cls in OPENINGS:
                self.placed.append((self.box[X], self.box[X] + self.box[W]))

    def banned(self) -> list[int]:
        """Номера токенов-чисел, запрещённых следующим; пусто — если запрещать нечего или
        запретилось бы всё (тогда брак поймает валидатор)."""
        if self.cls is not ElementClass.WINDOW or not 0 <= self.at < len(self.walls):
            return []
        wall = self.walls[self.at]
        busy = wall.busy + self.placed
        if len(self.box) == X:
            bad = [n for n in self.vocab.token if n >= wall.length
                   or any(a <= n < b for a, b in busy)]
        elif len(self.box) == W:
            x = self.box[X]
            bad = [n for n in self.vocab.token if x + n > wall.length
                   or any(x < b and x + n > a for a, b in busy)]
        else:
            return []
        return [] if len(bad) == len(self.vocab.token) else [self.vocab.token[n] for n in bad]


def walls(bare: FacadeSheet, mode: Mode, cfg: Config) -> list[Wall]:
    """Стены дома в шагах сетки — как их видит модель в условии (`tokens.condition`)."""
    t = cfg.tokens
    out = []
    for f in bare.facades:
        zones = [(tokens.units(z.x0_m, t), tokens.units(z.x1_m, t)) for z in f.side.forbidden]
        given = [(tokens.units(o.x_m, t), tokens.units(o.x_m + o.width_m, t))
                 for o in f.side.openings if tokens.given(o.kind, mode)]
        out.append(Wall(tokens.units(f.side.length_m, t), zones + given))
    return out


def guard(bare: FacadeSheet, mode: Mode, vocab: Vocab, cfg: Config) -> WallGeometry | None:
    """Страж для ответа на этот дом; в режиме «окна из плана» — None, запрещать нечего.
    Включён ли запрет в конвейере — решает вызывающий (config/models.toml, `constrain`)."""
    if mode is not Mode.BLIND:
        return None
    return WallGeometry(walls(bare, mode, cfg), vocab)
