"""Запрет при генерации (gf#132): страж читает ответ модели и запрещает x и w окна, при которых
оно заходит в запретную зону, на проём или за край стены. torch не нужен — идёт и в CI."""

import numpy
import pytest
from simple_house import WALL_INTO_WINDOW, before_leaf

from genfacade import schema
from genfacade.schema import ElementClass, Mode, ZoneRole
from genfacade.train import constraints, tokens
from genfacade.train.tokens import Mark

# Стена 8 м (160 шагов по 5 см): запретная зона 3,9–4,1 м, вход 1,4–2,3 м; самое узкое окно —
# 12 шагов (0,6 м).
WALL = constraints.Wall(160, [(78, 82), (28, 46)])
NARROWEST = 12
NORMS = constraints.Norms(NARROWEST)
# все правила свода в страже (gf#213): угол 1 м, простенок 0,5 м, линия верха ±5 см, типоразмеры
STRICT = constraints.Norms(NARROWEST, corner=20, pier=10, head=1, types=(3, 4, 3))


@pytest.fixture
def vocab(cfg):
    return constraints.Vocab(tokens.vocabulary(cfg))


@pytest.fixture
def guard(cfg, vocab):
    """Страж одной стены WALL, прочитавший слова ответа; числа — сами числа."""
    ids = {w: i for i, w in enumerate(tokens.vocabulary(cfg))}

    def read(*words):
        g = constraints.WallGeometry([WALL], vocab, NORMS)
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


@pytest.fixture
def keep(cfg):
    """Слова, которые страж оставил следующим."""
    words = tokens.vocabulary(cfg)
    return lambda g: {w for i, w in enumerate(words) if i not in set(g.banned())}


def test_box_takes_only_numbers_inside_the_wall(guard, vocab, cfg):
    """Рамка — числа в пределах стены: на реальных домах карниз выходил выше стены на 1,7 м
    (gf#197); карниз стены неизвестен — по высоте предела нет."""
    numbers = set(vocab.token)
    assert _allowed(guard(Mark.WALL, WINDOW, 52), vocab) == numbers       # y — любое число
    assert _allowed(guard(Mark.WALL, DOOR), vocab) == set(range(160))     # x — на стене
    assert _allowed(guard(Mark.WALL, DOOR, 30, 10), vocab) == set(range(1, 131))  # до конца
    assert _allowed(guard(Mark.WALL, WINDOW, 52, 10, 20), vocab) == numbers - {0}  # высота > 0
    ids = {w: i for i, w in enumerate(tokens.vocabulary(cfg))}
    g = constraints.WallGeometry([WALL._replace(height=60)], vocab, NORMS)
    for w in (Mark.WALL, tokens.tok(ElementClass.CORNICE), 0):
        g.step(ids[str(w)])
    assert _allowed(g, vocab) == set(range(60))                           # y — ниже карниза
    for w in (50, 160):
        g.step(ids[str(w)])
    assert _allowed(g, vocab) == set(range(1, 11))                        # верх — не выше


def test_answer_follows_grammar(guard, keep):
    """Следующим — только то, что разберёт `tokens.decode`: сбитая модель писала токен условия,
    поле не по порядку, лишнее число зоны (план GenPlan, глухой режим, gf#177)."""
    window = (Mark.WALL, WINDOW, 52, 10, 20, 30)
    assert keep(guard()) == {Mark.WALL}                                  # ответ — со стены
    after_box = keep(guard(*window))
    assert {Mark.FLOOR, Mark.END, WINDOW, ZONE, "var:regular"} \
        <= after_box                                                      # поля, элемент, конец
    assert "fix:x_m" not in after_box                                     # `fix:` — у проёма плана
    assert not after_box & {"50", Mark.HOUSE, Mark.WALL, "kind:brick"}    # «12 32 10 36 50»
    assert "var:regular" not in keep(guard(*window, "fix:w_m"))          # поля — по порядку
    door = keep(guard(Mark.WALL, DOOR, 30, 0, 18, 42))
    assert "var:transom" not in after_box and "var:transom" in door      # вид — по классу
    assert Mark.FLOOR not in keep(guard(*window, Mark.FLOOR, 1))
    zone = (Mark.WALL, ZONE)
    assert keep(guard(*zone)) == {tokens.tok(r) for r in schema.PaletteRole}
    assert "0" not in keep(guard(*zone, "mat:accent"))                  # точек больше нуля
    points = keep(guard(*zone, "mat:accent", 2, 0, 10, 8, 10))
    assert not {str(n) for n in range(200)} & points and WINDOW not in points  # 2 точки, зоны
    assert guard(*window, Mark.END).banned() == []                        # ответ кончился


def test_wall_count_decides_end(cfg, vocab, keep):
    ids = {w: i for i, w in enumerate(tokens.vocabulary(cfg))}
    g = constraints.WallGeometry([WALL, WALL], vocab, NORMS)
    for w in (Mark.WALL, ZONE, "mat:main", 1, 0, 0):
        g.step(ids[str(w)])
    keep = keep(g)
    assert Mark.WALL in keep and Mark.END not in keep                     # стен ещё две


def _read(g, cfg, *words):
    ids = {w: i for i, w in enumerate(tokens.vocabulary(cfg))}
    for w in words:
        g.step(ids[str(w)])
    return g


def test_plan_openings_are_written_by_the_condition(cfg, lay_out, vocab, keep):
    """Проём плана — числами условия: x и ширина проёма, `fix:x_m fix:w_m`, и стену не кончить,
    пока он не поставлен; на реальных домах он пропадал или смещался (gf#197)."""
    bare = tokens.bare(lay_out(Mode.WITH_OPENINGS))
    g = constraints.guard(bare, Mode.WITH_OPENINGS, vocab, cfg)
    plan = g.walls[0].plan
    first = next(p for p in plan if p.cls is ElementClass.WINDOW)
    start = keep(_read(g, cfg, Mark.WALL))
    assert not start & {ZONE, Mark.WALL, Mark.END, tokens.tok(ElementClass.CORNICE)}  # сперва план
    assert _allowed(_read(g, cfg, WINDOW), vocab) == {first.x}
    assert _allowed(_read(g, cfg, first.x, 0), vocab) == {first.w}
    assert keep(_read(g, cfg, first.w, 30)) == {Mark.FLOOR}                 # этаж — обязательно
    assert _allowed(_read(g, cfg, Mark.FLOOR), vocab) == {1}                # первый
    tail = keep(_read(g, cfg, 1))
    assert "fix:x_m" in tail and not tail & {"fix:w_m", WINDOW, ZONE, Mark.END}  # поля по порядку
    assert keep(_read(g, cfg, "fix:x_m")) & {"fix:w_m", WINDOW} == {"fix:w_m"}
    rest = [p for p in plan if p is not first]
    assert not rest or ZONE not in keep(_read(g, cfg, "fix:w_m"))           # остальные — следом


def test_floor_and_parent_are_ones_the_wall_has(guard, cfg, vocab, keep):
    """Этаж — из этажей дома, родитель — уже написанный элемент стены: на реальном доме модель
    писала «родитель 28», и ответ не разбирался (gf#197)."""
    first = (Mark.WALL, WINDOW, 52, 10, 20, 30)
    assert Mark.PARENT not in keep(guard(*first))                        # родителя ещё нет
    assert _allowed(guard(*first, Mark.FLOOR), vocab) == {1}             # стена в один этаж
    sill = (*first, tokens.tok(ElementClass.SILL), 52, 8, 20, 2, Mark.PARENT)
    assert _allowed(guard(*sill), vocab) == {0}


def test_own_window_does_not_cover_a_plan_opening(cfg, vocab):
    """«Окна из плана»: своё окно модели — не на проёме плана: у широкого окна GenPlan модель
    ставила рядом своё, и они пересекались (14 из 20 на двух этажах, gf#197)."""
    plan = constraints.Planned(ElementClass.WINDOW, 33, 15)
    wall = constraints.Wall(160, [], [(33, 48)], plan=(plan,))
    g = _read(constraints.WallGeometry([wall], vocab, NORMS), cfg,
              Mark.WALL, WINDOW, 33, 10, 15, 30, Mark.FLOOR, 1, "fix:x_m", "fix:w_m", WINDOW)
    assert not set(range(22, 48)) & _allowed(g, vocab)                    # не налезть на 33–48
    assert {0, 48, 148} <= _allowed(g, vocab)


def test_materials_only_from_the_house_palette(cfg, vocab, keep):
    """Материал — из палитры дома: у реального дома она одна (main), лист с цоколем из `plinth`
    схема не принимает (gf#197)."""
    g = constraints.WallGeometry([WALL], vocab, NORMS, {schema.PaletteRole.MAIN})
    assert keep(_read(g, cfg, Mark.WALL, ZONE)) == {"mat:main"}
    window = keep(_read(constraints.WallGeometry([WALL], vocab, NORMS,
                                                 {schema.PaletteRole.MAIN}), cfg,
                        Mark.WALL, WINDOW, 52, 10, 20, 30))
    assert "mat:main" in window and "mat:trim" not in window


def test_zone_is_a_rectangle_on_the_wall(cfg, vocab):
    """Зона — прямоугольник на стене, как все зоны корпуса: (x0 y0) (x1 y0) (x1 y1) (x0 y1), x до
    длины, y до карниза; зоны модели торчали за стену треугольниками (gf#197)."""
    g = _read(constraints.WallGeometry([WALL._replace(height=60)], vocab, NORMS), cfg,
              Mark.WALL, ZONE, "mat:main")
    assert _allowed(g, vocab) == {4}                                      # четыре точки
    steps = [(4, set(range(160))), (10, set(range(60))), (20, set(range(11, 161))), (90, {20}),
             (20, {90}), (90, set(range(21, 61))), (50, {10}), (10, {50})]
    for word, allowed in steps:
        assert _allowed(_read(g, cfg, word), vocab) == allowed
    edge = _read(constraints.WallGeometry([WALL._replace(height=60)], vocab, NORMS), cfg,
                 Mark.WALL, ZONE, "mat:main", 4)
    assert 160 not in _allowed(edge, vocab)    # угол на краю — правее места нет, всё запрещено


def test_plan_entrance_is_kept_in_blind_mode(cfg, lay_out, vocab):
    bare = tokens.bare(lay_out(Mode.BLIND))
    g = constraints.guard(bare, Mode.BLIND, vocab, cfg)
    door = next(p for p in g.walls[0].plan if p.cls is ElementClass.DOOR)
    assert _allowed(_read(g, cfg, Mark.WALL, DOOR), vocab) == {door.x}       # вход — по условию
    assert all(p.cls is ElementClass.DOOR for w in g.walls for p in w.plan)  # окна — модели


def test_guard_walls_in_blind_mode(cfg, lay_out, vocab):
    bare = tokens.bare(lay_out(Mode.BLIND))
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
    g = constraints.WallGeometry([TWO], vocab, NORMS)
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
    # на первом этаже то же x уже занято — годной ширины нет: только предел стены, брак — валидатору
    taken = _two_storey(vocab, ids, *first, WINDOW, 100, 20)
    assert _allowed(taken, vocab) == set(range(1, 61))
    # x годен только на втором этаже (зона первого) — y только на втором: от 60 шагов
    in_zone = _allowed(_two_storey(vocab, ids, Mark.WALL, WINDOW, 79), vocab)
    assert in_zone == {n for n in vocab.token if n >= 60}
    # x годен на обоих этажах — y любой
    assert _allowed(_two_storey(vocab, ids, Mark.WALL, WINDOW, 100), vocab) == set(vocab.token)
    # второе окно второго этажа обходит первое окно второго этажа
    second = (*first, WINDOW, 100, 70, 20, 30, WINDOW, 90, 70)
    assert _allowed(_two_storey(vocab, ids, *second), vocab) == set(range(1, 11))


@pytest.mark.parametrize(("x0", "x1", "span"), [
    (1.9297, 2.0059, (38, 40)),   # план GenPlan: к ближнему узлу — 39–40, окно до 1,95 заходит
    (3.9, 4.1, (78, 82)),         # на узлах — как есть
    (1.0, 1.005, (20, 20)),       # уже допуска валидатора — не занимает ничего
])
def test_zone_on_grid_covers_real_zone(cfg, lay_out, vocab, x0, x1, span):
    """Окно, которое страж пускает впритык к зоне на сетке, валидатор не бракует: зона на сетке
    покрывает настоящую с допуском `eps_m`."""
    zone = schema.ForbiddenZone(x0_m=x0, x1_m=x1)
    assert _second_wall(cfg, lay_out, Mode.BLIND, forbidden=[zone]).ground == [span]


def _second_wall(cfg, lay_out, mode, **side):
    """Вторая стена простого дома в шагах сетки, у стороны которой поля side заменены."""
    bare = tokens.bare(lay_out(mode))
    facades = list(bare.facades)
    facades[1] = facades[1].model_copy(update={"side": facades[1].side.model_copy(update=side)})
    return constraints.walls(bare.model_copy(update={"facades": facades}), mode, cfg)[1]


@pytest.mark.parametrize("mode", list(Mode))
def test_guard_never_bans_every_token(cfg, lay_out, vocab, mode):
    """Случайный ответ, которому страж не мешает: на каждом шаге есть что выбрать — иначе сэмплер
    получает NaN (план GenPlan: угол зоны на краю стены, gf#197)."""
    bare = tokens.bare(lay_out(mode))
    for seed in range(20):
        rng, g = numpy.random.default_rng(seed), constraints.guard(bare, mode, vocab, cfg)
        if seed % 2:  # и со всеми правилами свода (gf#213)
            g = constraints.WallGeometry(g.walls, vocab, STRICT)
        for _ in range(400):
            banned = set(g.banned())
            free = [i for i in range(vocab.size) if i not in banned]
            assert free
            token = int(rng.choice(free))
            if token == vocab.end:
                break
            g.step(token)


def test_plan_opening_takes_its_real_metres(cfg, lay_out):
    """Проём плана не на сетке занимает свои настоящие метры наружу, а не числа условия:
    привязка ставит его ровно на план, и окно модели впритык к числам условия 0,90–3,05 м
    заходило на окно плана 0,915–3,073 м на 2,3 см — страж пропускал, валидатор браковал
    (план GenPlan, gf#197, gf#213)."""
    window = schema.Opening(kind=schema.OpeningKind.WINDOW, x_m=0.915, width_m=2.158)
    wall = _second_wall(cfg, lay_out, Mode.WITH_OPENINGS, openings=[window], forbidden=[])
    assert (wall.plan[0].x, wall.plan[0].w) == (18, 43)   # условие — числа сетки
    assert wall.ground == wall.given == [(18, 62)]        # занято — до 3,10 м


def _strict(cfg, vocab, wall, *words, **rules):
    """Страж с правилами свода rules (gf#213), прочитавший слова ответа."""
    return _read(constraints.WallGeometry(wall, vocab, constraints.Norms(NARROWEST, **rules)),
                 cfg, *words)


def test_corner_distance_keeps_model_window_off_the_corners(cfg, vocab):
    """Правило свода `window_corner_distance`: окно модели — не ближе нормы к углу стены."""
    g = _strict(cfg, vocab, [WALL], Mark.WALL, WINDOW, corner=20)
    assert _allowed(g, vocab) == set(range(46, 78 - NARROWEST + 1)) | set(
        range(82, 160 - 20 - NARROWEST + 1))
    assert max(_allowed(_read(g, cfg, 82, 10), vocab)) == 160 - 20 - 82   # и правым краем
    short = _strict(cfg, vocab, [constraints.Wall(30, [])], Mark.WALL, WINDOW, corner=20)
    assert _allowed(short, vocab)                       # не выполнить — как без неё


def test_pier_keeps_model_window_off_other_openings(cfg, vocab):
    """Правило свода `pier_min`: между проёмами этажа — простенок не уже нормы, и от окна
    модели, и от проёма плана."""
    g = _strict(cfg, vocab, [WALL], Mark.WALL, WINDOW, 100, 10, 20, 30, WINDOW, pier=10)
    assert _allowed(g, vocab) == set(range(0, 28 - NARROWEST + 1)) | set(
        range(46, 78 - NARROWEST + 1)) | set(range(130, 160 - NARROWEST + 1))
    plan = constraints.Wall(160, [], [(28, 46)], given=[(28, 46)])
    g = _strict(cfg, vocab, [plan], Mark.WALL, WINDOW, pier=10)
    assert not set(range(28 - 10 - NARROWEST + 1, 46 + 10)) & _allowed(g, vocab)


def test_head_line_puts_window_tops_of_a_floor_on_one_line(cfg, vocab):
    """Правило свода `window_head_line`: верх окна — на линии верха окон своего этажа стены
    (допуск — шаг сетки); у окна другого этажа своя линия."""
    first = (Mark.WALL, WINDOW, 100, 10, 20, 30, WINDOW)     # верх — 40, первый этаж
    assert _allowed(_strict(cfg, vocab, [TWO], *first, 20, 12, 10, head=1), vocab) == {27, 28, 29}
    upper = _allowed(_strict(cfg, vocab, [TWO], *first, 20, 70, 10, head=1), vocab)
    assert upper == set(vocab.token) - {0}                    # второй этаж — своя линия


def test_window_sizes_come_from_the_house_types(cfg, vocab):
    """Правило свода `window_types`: когда типоразмеров окон на стене или в доме уже столько,
    сколько допускает правило, следующее окно — одного из них (в допуске)."""
    first = (Mark.WALL, WINDOW, 100, 10, 20, 30, WINDOW, 130, 10)
    g = _strict(cfg, vocab, [WALL], *first, types=(1, 4, 3))
    assert _allowed(g, vocab) == set(range(17, 24))                   # ширина — 20 ± 3
    assert _allowed(_read(g, cfg, 22), vocab) == set(range(27, 34))   # высота — 30 ± 3
    house = _strict(cfg, vocab, [WALL, WALL], Mark.WALL, WINDOW, 100, 10, 20, 30,
                    Mark.WALL, WINDOW, 130, 10, types=(3, 1, 3))
    assert _allowed(house, vocab) == set(range(17, 24))               # на другой стене — тоже
