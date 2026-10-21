"""Запрет при генерации (gf#132): страж читает ответ модели и запрещает x и w окна, при которых
оно заходит в запретную зону, на проём или за край стены. torch не нужен — идёт и в CI."""

import pytest
from simple_house import WALL_INTO_WINDOW, before_leaf

from genfacade.schema import ElementClass, Mode, ZoneRole
from genfacade.train import constraints, tokens
from genfacade.train.tokens import Mark

# Стена 8 м (160 шагов по 5 см): запретная зона 3,9–4,1 м, вход 1,4–2,3 м; самое узкое окно —
# 12 шагов (0,6 м).
WALL = constraints.Wall(160, [(78, 82), (28, 46)])
NARROWEST = 12


@pytest.fixture
def vocab(cfg):
    return constraints.Vocab(tokens.vocabulary(cfg))


@pytest.fixture
def guard(cfg, vocab):
    """Страж одной стены WALL, прочитавший слова ответа; числа — сами числа."""
    ids = {w: i for i, w in enumerate(tokens.vocabulary(cfg))}

    def read(*words):
        g = constraints.WallGeometry([WALL], vocab, NARROWEST)
        for w in words:
            g.step(ids[str(w)])
        return g

    return read


def _allowed(g, vocab) -> set[int]:
    """Числа, которые страж оставил; заодно — всё нечисловое запрещено."""
    banned = set(g.banned())
    assert set(range(vocab.size)) - set(vocab.number) <= banned
    return {n for i, n in vocab.number.items() if i not in banned}


WINDOW, DOOR, ZONE = (tokens.tok(v) for v in (ElementClass.WINDOW, ElementClass.DOOR,
                                              ZoneRole.MAIN))


def test_window_x_avoids_zones_entrance_and_wall_end(guard, vocab):
    """x окна — только там, где до входа, зоны или края стены помещается самое узкое окно."""
    ok = _allowed(guard(Mark.WALL, WINDOW), vocab)
    assert ok == set(range(0, 28 - NARROWEST + 1)) | set(range(46, 78 - NARROWEST + 1)) \
        | set(range(82, 160 - NARROWEST + 1))


def test_window_width_stops_at_next_busy_span_and_is_remembered(guard, vocab):
    # 52 + 26 = 78 — край зоны: касаться можно; ширина 0 — не окно
    assert _allowed(guard(Mark.WALL, WINDOW, 52, 10), vocab) == set(range(1, 27))
    g = guard(Mark.WALL, WINDOW, 52, 10, 20, 30, WINDOW)
    assert not set(range(52, 72)) & _allowed(g, vocab)   # поставленное окно 52–72 занято


def test_box_takes_only_numbers_and_nothing_is_banned_outside_it(guard, vocab):
    numbers = set(vocab.token)
    assert guard(WINDOW).banned() == []                                   # до первой стены
    assert _allowed(guard(Mark.WALL, WINDOW, 52), vocab) == numbers       # y — любое число
    assert _allowed(guard(Mark.WALL, DOOR), vocab) == numbers             # x двери — из плана
    assert _allowed(guard(Mark.WALL, DOOR, 30, 10), vocab) == numbers - {0}   # ширина > 0
    # рамка дописана: следующим — не число (лишнее число ломает ответ, gf#177), дальше — свободно
    assert set(guard(Mark.WALL, WINDOW, 52, 10, 20, 30).banned()) == set(vocab.number)
    assert guard(Mark.WALL, WINDOW, 52, 10, 20, 30, Mark.FLOOR).banned() == []
    assert guard(Mark.WALL, WINDOW, 52, 10, 20, 30, ZONE).banned() == []  # числа зоны


def test_guard_only_in_blind_mode(cfg, lay_out, vocab):
    bare = tokens.bare(lay_out(Mode.BLIND))
    assert constraints.guard(bare, Mode.WITH_OPENINGS, vocab, cfg) is None
    walls = constraints.guard(bare, Mode.BLIND, vocab, cfg).walls
    front = bare.facades[0].side
    door = next(o for o in front.openings if tokens.given(o.kind, Mode.BLIND))
    x = tokens.units(door.x_m, cfg.tokens)
    assert walls[0].length == tokens.units(front.length_m, cfg.tokens)
    assert (x, tokens.units(door.x_m + door.width_m, cfg.tokens)) in walls[0].ground  # 1-й этаж


def test_forbidden_zones_belong_to_ground_floor(cfg, lay_out, simple_svg, vocab):
    """Зоны — по плану первого этажа (`evaluation: Запретные зоны — по плану этажа`): страж
    держит их только для первого этажа."""
    bare = tokens.bare(lay_out(Mode.BLIND, svg=simple_svg(before_leaf(WALL_INTO_WINDOW))))
    walls = constraints.guard(bare, Mode.BLIND, vocab, cfg).walls
    assert any(f.side.forbidden for f in bare.facades)
    for f, wall in zip(bare.facades, walls, strict=True):
        zones = {(tokens.units(z.x0_m, cfg.tokens), tokens.units(z.x1_m, cfg.tokens))
                 for z in f.side.forbidden}
        assert wall.busy == [] and zones <= set(wall.ground)


# Та же стена в два этажа: низ второго — 3,0 м (60 шагов); зона и вход — план первого этажа.
TWO = constraints.Wall(160, [], [(78, 82), (28, 46)], (60,))


def _two_storey(vocab, ids, *words):
    g = constraints.WallGeometry([TWO], vocab, NARROWEST)
    for w in words:
        g.step(ids[str(w)])
    return g


def test_two_storey_wall_keeps_floors_apart(cfg, vocab):
    """`generation: Окна вне запретных зон` на двух этажах: этаж — по y, второму числу рамки.
    Окно второго этажа над окном первого, над входом и над запретной зоной годно — зона по плану
    первого этажа (`evaluation: Запретные зоны — по плану этажа`); окна этажа не пересекаются."""
    ids = {w: i for i, w in enumerate(tokens.vocabulary(cfg))}
    first = (Mark.WALL, WINDOW, 100, 20, 20, 30)            # окно первого этажа 100–120
    # x: над входом и над зоной — годен (на втором этаже они не заняты)
    assert {30, 70, 100} <= _allowed(_two_storey(vocab, ids, *first, WINDOW), vocab)
    # w окна первого этажа упирается в зону, окна второго — проходит над ней
    assert _allowed(_two_storey(vocab, ids, Mark.WALL, WINDOW, 70, 20), vocab) == set(range(1, 9))
    assert _allowed(_two_storey(vocab, ids, Mark.WALL, WINDOW, 70, 70), vocab) == set(range(1, 91))
    # w окна второго этажа над окном первого: до края стены
    assert _allowed(_two_storey(vocab, ids, *first, WINDOW, 100, 70), vocab) == set(range(1, 61))
    # на первом этаже то же x уже занято — годной ширины нет, страж не запрещает ничего
    assert _two_storey(vocab, ids, *first, WINDOW, 100, 20).banned() == []
    # второе окно второго этажа обходит первое окно второго этажа
    second = (*first, WINDOW, 100, 70, 20, 30, WINDOW, 90, 70)
    assert _allowed(_two_storey(vocab, ids, *second), vocab) == set(range(1, 11))
