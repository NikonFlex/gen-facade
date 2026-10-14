"""Запрет при генерации (gf#132): страж читает ответ модели и запрещает x и w окна, при которых
оно заходит в запретную зону, на проём или за край стены. torch не нужен — идёт и в CI."""

import pytest

from genfacade.schema import ElementClass, Mode, ZoneRole
from genfacade.train import constraints, tokens
from genfacade.train.tokens import Mark

# Стена 8 м (160 шагов по 5 см): запретная зона 3,9–4,1 м, вход 1,4–2,3 м.
WALL = constraints.Wall(160, [(78, 82), (28, 46)])


@pytest.fixture
def vocab(cfg):
    return constraints.Vocab(tokens.vocabulary(cfg))


@pytest.fixture
def guard(cfg, vocab):
    """Страж одной стены WALL, прочитавший слова ответа; числа — сами числа."""
    ids = {w: i for i, w in enumerate(tokens.vocabulary(cfg))}

    def read(*words):
        g = constraints.WallGeometry([WALL], vocab)
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
    ok = _allowed(guard(Mark.WALL, WINDOW), vocab)
    assert ok == set(range(0, 28)) | set(range(46, 78)) | set(range(82, 160))


def test_window_width_stops_at_next_busy_span_and_is_remembered(guard, vocab):
    # 52 + 26 = 78 — край зоны: касаться можно; ширина 0 — не окно
    assert _allowed(guard(Mark.WALL, WINDOW, 52, 10), vocab) == set(range(1, 27))
    g = guard(Mark.WALL, WINDOW, 52, 10, 20, 30, WINDOW)
    assert not set(range(52, 72)) & _allowed(g, vocab)   # поставленное окно 52–72 занято


def test_no_bans_outside_window_box(guard):
    assert guard(WINDOW).banned() == []                              # до первой стены
    assert guard(Mark.WALL, WINDOW, 52).banned() == []               # пишется y
    assert guard(Mark.WALL, DOOR).banned() == []                     # дверь — из плана
    assert guard(Mark.WALL, WINDOW, 52, 10, 20, 30, ZONE).banned() == []  # числа зоны


def test_guard_only_in_blind_mode(cfg, lay_out, vocab):
    bare = tokens.bare(lay_out(Mode.BLIND))
    assert constraints.guard(bare, Mode.WITH_OPENINGS, vocab, cfg) is None
    walls = constraints.guard(bare, Mode.BLIND, vocab, cfg).walls
    front = bare.facades[0].side
    door = next(o for o in front.openings if tokens.given(o.kind, Mode.BLIND))
    x = tokens.units(door.x_m, cfg.tokens)
    assert walls[0].length == tokens.units(front.length_m, cfg.tokens)
    assert (x, tokens.units(door.x_m + door.width_m, cfg.tokens)) in walls[0].busy
