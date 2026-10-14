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


def _banned(g, vocab) -> set[int]:
    return {vocab.number[i] for i in g.banned()}


WINDOW, DOOR, ZONE = (tokens.tok(v) for v in (ElementClass.WINDOW, ElementClass.DOOR,
                                              ZoneRole.MAIN))


def test_window_x_avoids_zones_entrance_and_wall_end(guard, vocab):
    g = guard(Mark.WALL, WINDOW)
    bad = _banned(g, vocab)
    assert set(range(78, 82)) <= bad and set(range(28, 46)) <= bad
    assert {n for n in vocab.token if n >= 160} <= bad
    assert not {0, 27, 46, 50, 77, 82, 159} & bad


def test_window_width_stops_at_next_busy_span_and_is_remembered(guard, vocab):
    g = guard(Mark.WALL, WINDOW, 52, 10)
    bad = _banned(g, vocab)
    assert 26 not in bad and 27 in bad          # 52 + 26 = 78 — край зоны: касаться можно
    g = guard(Mark.WALL, WINDOW, 52, 10, 20, 30, WINDOW)
    assert set(range(52, 72)) <= _banned(g, vocab)   # поставленное окно 52–72 занято


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
