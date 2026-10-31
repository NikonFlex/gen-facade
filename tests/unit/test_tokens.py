"""Дом как последовательность токенов: запись, разбор, словарь
(`generation: Раскладка — последовательность токенов`; gf#73)."""

import math

import pytest

from genfacade import derive
from genfacade.datasets.synthetic import build
from genfacade.schema import ElementClass, FixedField, Mode, OpeningKind, Rule, Trim, VariantKind
from genfacade.train import tokens
from genfacade.train.tokens import Mark, TokenError
from genfacade.unfold import unfold
from genfacade.validate import validate

SEEDS = range(40)


@pytest.fixture(scope="module")
def sheets(cfg):
    return [build.sample(s, cfg).sheet for s in SEEDS]


def _on_grid(v: float, cfg) -> float:
    """Ближайший узел сетки; ровно полшага — вверх."""
    return round(math.floor(v / cfg.tokens.grid_m + 0.5 + 1e-6) * cfg.tokens.grid_m, 6)


def _expected(sheet, mode, cfg):
    """Тот же дом, каким он должен вернуться: края на сетке, имена по месту, поля по режиму;
    подоконники, наличники, ставни, козырьки — выведены кодом по признакам (gf#212)."""
    g = lambda v: _on_grid(v, cfg)  # noqa: E731 — короткая запись в одном тесте
    step = cfg.tokens.grid_m
    out = []
    for f in sheet.facades:
        written = tokens.ordered(f, mode, cfg.tokens)  # проёмы плана — первыми, как у стража
        names = {e.id: tokens.name(i) for i, e in enumerate(written)}
        elements = []
        for e in written:
            blind = mode is Mode.BLIND and e.cls is ElementClass.WINDOW
            elements.append(e.model_copy(update={
                "id": names[e.id], "parent": names.get(e.parent), "x_m": g(e.x_m), "y_m": g(e.y_m),
                "w_m": round(max(step, g(e.x_m + e.w_m) - g(e.x_m)), 6),
                "h_m": round(max(step, g(e.y_m + e.h_m) - g(e.y_m)), 6),
                "fixed": [] if blind else e.fixed}))
        marks = {names[k]: v for k, v in derive.flags(f.elements).items()}
        wall = derive.Wall(sheet.spec, f.side.length_m, cfg.derive)
        zones = [z.model_copy(update={"shape": [(g(x), g(y)) for x, y in z.shape]})
                 for z in f.zones]
        out.append(f.model_copy(update={"elements": derive.place(elements, marks, wall),
                                        "zones": zones}))
    return sheet.model_copy(update={"facades": out})


def _in_answer_order(sheet, mode, cfg):
    """Тот же дом, элементы стен — в порядке ответа (`tokens.ordered`) и с выведенными по нему."""
    out = []
    for f in sheet.facades:
        wall = derive.Wall(sheet.spec, f.side.length_m, cfg.derive)
        placed = derive.place(tokens.ordered(f, mode, cfg.tokens), derive.flags(f.elements), wall)
        out.append(f.model_copy(update={"elements": placed}))
    return sheet.model_copy(update={"facades": out})


def _round_trip(sheet, mode, cfg):
    """Ответ записан токенами и разобран обратно на стены того же дома."""
    return tokens.decode(tokens.answer(sheet, mode, cfg), tokens.bare(sheet), cfg)


@pytest.mark.parametrize("mode", list(Mode))
def test_answer_decodes_to_the_same_house(sheets, cfg, mode):
    """Запись → разбор возвращает тот же дом с точностью до сетки и имён элементов."""
    for sheet in sheets:
        back = _round_trip(sheet, mode, cfg)
        assert back == _expected(sheet, mode, cfg)


@pytest.mark.parametrize("mode", list(Mode))
def test_house_on_grid_still_valid_and_close(sheets, cfg, mode):
    """После сетки дом проходит валидатор без единого замечания и сдвинут меньше чем на шаг."""
    for sheet in sheets:
        back = _round_trip(sheet, mode, cfg)
        rules = {v.rule for v in validate(back, cfg.checks)}
        # в режиме 1 окна в ответе не помечены заданными — на привязку к плану это не влияет
        assert rules == set(), rules
        for was, now in zip(_in_answer_order(sheet, mode, cfg).facades, back.facades, strict=True):
            for a, b in zip(was.elements, now.elements, strict=True):
                assert abs(a.x_m - b.x_m) <= cfg.tokens.grid_m / 2 + 1e-9
                assert abs(a.y_m - b.y_m) <= cfg.tokens.grid_m / 2 + 1e-9


def _one(sheet, cfg, cls=ElementClass.DOOR, **box):
    """Дом с одним элементом с заданными координатами — после записи и разбора."""
    door = next(e for f in sheet.facades for e in f.elements if e.cls is ElementClass.DOOR)
    wall = sheet.facades[0].model_copy(update={
        "elements": [door.model_copy(update={"cls": cls, "variant": None, "fixed": [], **box})],
        "zones": []})
    one = sheet.model_copy(update={"facades": [wall]})
    return tokens.decode(tokens.answer(one, Mode.BLIND, cfg), one, cfg).facades[0].elements[0]


def test_edges_go_to_grid_not_sizes(sheets, cfg):
    """На сетку встают края: правый край 2.03 → 2.05, значит ширина 1.05, а не 1.0."""
    e = _one(sheets[0], cfg, x_m=1.02, w_m=1.01, y_m=1.0, h_m=1.0)
    assert (e.x_m, e.w_m) == (1.0, 1.05)


def test_thin_detail_keeps_one_step(sheets, cfg):
    """Карниз 1 см на сетке 5 см не исчезает: высота — один шаг."""
    e = _one(sheets[0], cfg, cls=ElementClass.CORNICE, y_m=1.01, h_m=0.01)
    assert e.h_m == cfg.tokens.grid_m


def test_half_step_always_rounds_up(sheets, cfg):
    """Верх 2.975 м у двух элементов разной высоты встаёт на одну линию, а не на соседние."""
    found = [_one(sheets[0], cfg, y_m=y, h_m=round(2.975 - y, 3)) for y in (1.05, 2.013, 0.5)]
    assert {round(e.y_m + e.h_m, 6) for e in found} == {3.0}


def _windows(sheet):
    return [e for f in sheet.facades for e in f.elements if e.cls is ElementClass.WINDOW]


def test_windows_refer_to_house_sizes(sheets, cfg):
    """Окно пишется номером типоразмера дома, а не шириной и высотой (gf#212): у дома после разбора
    окон разных размеров не больше, чем типоразмеров в начале ответа, и не больше window_types."""
    for sheet in sheets:
        for mode in Mode:
            answer = tokens.answer(sheet, mode, cfg)
            count = int(answer[answer.index(Mark.TYPES) + 1])
            back = tokens.decode(answer, tokens.bare(sheet), cfg)
            sizes = {(round(w.w_m, 6), round(w.h_m, 6)) for w in _windows(back)}
            assert len(sizes) <= count <= tokens.window_types(cfg)
            assert not [t for t in answer if t.startswith(tokens.tok(ElementClass.SILL))]


def test_many_sizes_go_to_nearest_type(sheets, cfg):
    """У реального дома окон разных размеров больше, чем типоразмеров: окна — к ближнему, у дома
    после разбора их не больше window_types."""
    sheet = sheets[0]
    wall = sheet.facades[0]
    door = next(e for e in wall.elements if e.cls is ElementClass.DOOR)
    windows = [door.model_copy(update={
        "id": f"w{k}", "cls": ElementClass.WINDOW, "variant": None, "fixed": [], "floor": 1,
        "x_m": 0.5 + 1.6 * k, "w_m": 0.6 + 0.1 * k, "y_m": 1.0, "h_m": 1.2 + 0.05 * k})
        for k in range(6)]
    one = sheet.model_copy(update={"facades": [wall.model_copy(update={
        "elements": windows, "zones": []})]})
    back = tokens.decode(tokens.answer(one, Mode.BLIND, cfg), one, cfg)
    sizes = {(w.w_m, w.h_m) for w in _windows(back)}
    assert len(sizes) == tokens.window_types(cfg) < len(windows)
    assert all(abs(b.w_m - a.w_m) <= 0.1 + 1e-9 for a, b in zip(windows, _windows(back),
                                                                strict=True))


def test_trims_are_flags_of_their_opening(sheets, cfg):
    """Подоконник, наличник, ставни, козырёк — признак своего проёма, не элемент (gf#212); признак
    без вида у дома и признак не своего класса — брак."""
    words = [t for s in sheets for t in tokens.answer(s, Mode.BLIND, cfg)]
    derived = [tokens.tok(c) for c in derive.DERIVED.values()]
    assert not set(derived) & set(words)
    assert {tokens.tok(t) for t in Trim} <= set(words)
    sheet = next(s for s in sheets if not s.spec.trim.has(Trim.SHUTTERS))
    answer = tokens.answer(sheet, Mode.BLIND, cfg)
    def put(cls, trim):  # признак — последним полем элемента, перед заданными полями
        at = answer.index(tokens.tok(cls))
        end = next(i for i in range(at + 1, len(answer))
                   if answer[i].startswith(("cls:", "role:", Mark.WALL, "fix:")))
        return [*answer[:end], tokens.tok(trim), *answer[end:]]

    with pytest.raises(TokenError, match="у window, а не у door"):
        tokens.decode(put(ElementClass.DOOR, Trim.SILL), tokens.bare(sheet), cfg)
    with pytest.raises(TokenError, match="таких видов у дома нет"):
        tokens.decode(put(ElementClass.WINDOW, Trim.SHUTTERS), tokens.bare(sheet), cfg)


def test_every_token_is_in_vocabulary(sheets, cfg):
    vocab = tokens.vocabulary(cfg)
    assert len(vocab) == len(set(vocab))
    for sheet in sheets:
        for mode in Mode:
            assert set(tokens.encode(sheet, mode, cfg)) <= set(vocab)


def test_modes_differ_by_plan_windows(sheets, cfg):
    """Режим 2: окна плана — в условии и заданы в ответе. Режим 1: в условии только вход."""
    window, entrance = tokens.tok(OpeningKind.WINDOW), tokens.tok(OpeningKind.ENTRANCE)
    fixed = tokens.tok(FixedField.X)
    for sheet in sheets:
        plan_windows = sum(o.kind is OpeningKind.WINDOW for f in sheet.facades
                           for o in f.side.openings)
        given = tokens.condition(sheet, Mode.WITH_OPENINGS, cfg)
        blind = tokens.condition(sheet, Mode.BLIND, cfg)
        assert (given.count(window), blind.count(window)) == (plan_windows, 0)
        assert given.count(entrance) == blind.count(entrance) == 1
        answers = {m: tokens.answer(sheet, m, cfg) for m in Mode}
        assert answers[Mode.WITH_OPENINGS].count(fixed) == plan_windows + 1  # окна и вход
        assert answers[Mode.BLIND].count(fixed) == 1  # только вход


def test_condition_lists_walls_from_entrance(sheets, cfg):
    """Стены — по обходу от стороны входа: вход отмечен у первой стены."""
    for sheet in sheets:
        cond = tokens.condition(sheet, Mode.BLIND, cfg)
        sides = [i for i, t in enumerate(cond) if t == Mark.SIDE]
        assert len(sides) == len(sheet.facades)
        assert cond[sides[0] + 2] == Mark.ENTRANCE
        assert cond[sides[0] + 1] == str(round(sheet.facades[0].side.length_m / cfg.tokens.grid_m))


def _answer(sheets, cfg):
    return tokens.answer(sheets[0], Mode.WITH_OPENINGS, cfg)


def _broken(seq: list[str], what: str) -> list[str]:
    door = seq.index(tokens.tok(ElementClass.DOOR))
    return {
        "оборвалась": seq[:-1],
        "ждали <wall>": [s for s in seq if s != Mark.WALL] + [Mark.WALL],
        "ждали число": seq[:door + 1] + [str(Mark.FLOOR)] + seq[door + 2:],
        "такого номера в стене нет": _with_parent(seq, "99"),
        "ещё 1 токенов": seq + ["0"],
        "ждали <answer>": seq[1:],
        "ждали типоразмер": _with_size(seq, "size:9"),
        "greater than 0": seq[:door + 3] + ["0"] + seq[door + 4:],
        "greater than or equal to 1": _frame_rows(seq, "0"),
    }[what]


def _frame_rows(seq: list[str], rows: str) -> list[str]:
    """Деление рамы на ряды — второе число после вида проёма; недоученная модель пишет 0."""
    at = next(i for i, t in enumerate(seq) if t.startswith(f"{tokens.PREFIX[VariantKind]}:"))
    return seq[:at + 2] + [rows] + seq[at + 3:]


def _with_size(seq: list[str], size: str) -> list[str]:
    at = next(i for i, t in enumerate(seq) if t.startswith(f"{tokens.SIZE}:"))
    return seq[:at] + [size] + seq[at + 1:]


def _with_parent(seq: list[str], number: str) -> list[str]:
    at = seq.index(Mark.PARENT)
    return seq[:at + 1] + [number] + seq[at + 2:]


@pytest.mark.parametrize("what", [
    "оборвалась", "ждали <wall>", "ждали число", "такого номера в стене нет", "ещё 1 токенов",
    "ждали <answer>", "ждали типоразмер", "greater than 0", "greater than or equal to 1"])
def test_broken_answer_refused_with_reason(sheets, cfg, what):
    """Ответ модели бывает негодным: разбор не чинит его молча, а называет причину."""
    with pytest.raises(TokenError, match=what):
        tokens.decode(_broken(_answer(sheets, cfg), what), tokens.bare(sheets[0]), cfg)


def test_unknown_style_or_too_long_wall_cannot_be_written(sheets, cfg):
    sheet = sheets[0]
    odd = sheet.model_copy(update={"spec": sheet.spec.model_copy(update={"style": "gothic"})})
    with pytest.raises(TokenError, match="style:gothic"):
        tokens.condition(odd, Mode.BLIND, cfg)
    long_side = sheet.facades[0].side.model_copy(update={"length_m": cfg.tokens.max_m + 1})
    far = sheet.model_copy(update={"facades": [
        sheet.facades[0].model_copy(update={"side": long_side}), *sheet.facades[1:]]})
    with pytest.raises(TokenError, match="вне сетки"):
        tokens.condition(far, Mode.BLIND, cfg)


def test_wall_edges_off_grid_are_real_edges(sheets, cfg):
    """Сторона не на сетке (у GenPlan 4,2254 м — в условии 4,25): карниз и зоны, которые модель
    поставила на край стены в сетке, после разбора — ровно по настоящей стене; окно посреди стены
    не двигается (gf#153)."""
    sheet = sheets[0]
    off = cfg.tokens.grid_m * 0.49  # длина, которая округляется в тот же узел сетки
    walls = [f.model_copy(update={"side": f.side.model_copy(update={
        "length_m": f.side.length_m - off})}) for f in tokens.bare(sheet).facades]
    walls = unfold(sheet.model_copy(update={"facades": walls}))
    back = tokens.decode(tokens.answer(sheet, Mode.BLIND, cfg), walls, cfg)
    assert not [v for v in validate(back, cfg.checks) if v.rule is Rule.OUTSIDE]
    for was, now in zip(_in_answer_order(sheet, Mode.BLIND, cfg).facades, back.facades,
                        strict=True):
        length = now.side.length_m
        cornice = next(e for e in now.elements if e.cls is ElementClass.CORNICE)
        assert cornice.x_m + cornice.w_m == pytest.approx(length)
        assert max(x for z in now.zones for x, _ in z.shape) == pytest.approx(length)
        inner = [(a, b) for a, b in zip(was.elements, now.elements, strict=True)
                 if a.cls is ElementClass.WINDOW and a.x_m + a.w_m < length - cfg.tokens.grid_m]
        assert all(b.x_m + b.w_m == pytest.approx(a.x_m + a.w_m) for a, b in inner)
