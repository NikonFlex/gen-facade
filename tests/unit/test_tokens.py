"""Дом как последовательность токенов: запись, разбор, словарь (generation.md, п. 3; gf#73)."""

import math

import pytest

from genfacade.datasets.synthetic import build
from genfacade.schema import ElementClass, FixedField, Mode, OpeningKind
from genfacade.train import tokens
from genfacade.train.tokens import Mark, TokenError
from genfacade.validate import validate

SEEDS = range(40)


@pytest.fixture(scope="module")
def sheets(cfg):
    return [build.sample(s, cfg).sheet for s in SEEDS]


def _bare(sheet):
    """Дом после развёртки: стены без элементов и зон — то, что есть до ответа модели."""
    walls = [f.model_copy(update={"elements": [], "zones": []}) for f in sheet.facades]
    return sheet.model_copy(update={"facades": walls})


def _on_grid(v: float, cfg) -> float:
    """Ближайший узел сетки; ровно полшага — вверх."""
    return round(math.floor(v / cfg.tokens.grid_m + 0.5 + 1e-6) * cfg.tokens.grid_m, 6)


def _expected(sheet, mode, cfg):
    """Тот же дом, каким он должен вернуться: края на сетке, имена по месту, поля по режиму."""
    g = lambda v: _on_grid(v, cfg)  # noqa: E731 — короткая запись в одном тесте
    step = cfg.tokens.grid_m
    out = []
    for f in sheet.facades:
        names = {e.id: tokens.name(i) for i, e in enumerate(f.elements)}
        elements = []
        for e in f.elements:
            blind = mode is Mode.BLIND and e.cls is ElementClass.WINDOW
            elements.append(e.model_copy(update={
                "id": names[e.id], "parent": names.get(e.parent), "x_m": g(e.x_m), "y_m": g(e.y_m),
                "w_m": round(max(step, g(e.x_m + e.w_m) - g(e.x_m)), 6),
                "h_m": round(max(step, g(e.y_m + e.h_m) - g(e.y_m)), 6),
                "fixed": [] if blind else e.fixed}))
        zones = [z.model_copy(update={"shape": [(g(x), g(y)) for x, y in z.shape]})
                 for z in f.zones]
        out.append(f.model_copy(update={"elements": elements, "zones": zones}))
    return sheet.model_copy(update={"facades": out})


@pytest.mark.parametrize("mode", list(Mode))
def test_answer_decodes_to_the_same_house(sheets, cfg, mode):
    """Запись → разбор возвращает тот же дом с точностью до сетки и имён элементов."""
    for sheet in sheets:
        back = tokens.decode(tokens.answer(sheet, mode, cfg), _bare(sheet), cfg)
        assert back == _expected(sheet, mode, cfg)


@pytest.mark.parametrize("mode", list(Mode))
def test_house_on_grid_still_valid_and_close(sheets, cfg, mode):
    """После сетки дом проходит валидатор без единого замечания и сдвинут меньше чем на шаг."""
    for sheet in sheets:
        back = tokens.decode(tokens.answer(sheet, mode, cfg), _bare(sheet), cfg)
        rules = {v.rule for v in validate(back, cfg.checks)}
        # в режиме 1 окна в ответе не помечены заданными — на привязку к плану это не влияет
        assert rules == set(), rules
        for was, now in zip(sheet.facades, back.facades, strict=True):
            for a, b in zip(was.elements, now.elements, strict=True):
                assert abs(a.x_m - b.x_m) <= cfg.tokens.grid_m / 2 + 1e-9
                assert abs(a.y_m - b.y_m) <= cfg.tokens.grid_m / 2 + 1e-9


def _one_window(sheet, cfg, **box):
    """Дом с одним элементом — окном с заданными координатами — после записи и разбора."""
    window = next(e for f in sheet.facades for e in f.elements if e.cls is ElementClass.WINDOW)
    wall = sheet.facades[0].model_copy(update={
        "elements": [window.model_copy(update=box)], "zones": []})
    one = sheet.model_copy(update={"facades": [wall]})
    return tokens.decode(tokens.answer(one, Mode.BLIND, cfg), one, cfg).facades[0].elements[0]


def test_edges_go_to_grid_not_sizes(sheets, cfg):
    """На сетку встают края: правый край 2.03 → 2.05, значит ширина 1.05, а не 1.0."""
    e = _one_window(sheets[0], cfg, x_m=1.02, w_m=1.01, y_m=1.0, h_m=1.0)
    assert (e.x_m, e.w_m) == (1.0, 1.05)


def test_thin_detail_keeps_one_step(sheets, cfg):
    """Подоконник 1 см на сетке 5 см не исчезает: высота — один шаг."""
    e = _one_window(sheets[0], cfg, y_m=1.01, h_m=0.01)
    assert e.h_m == cfg.tokens.grid_m


def test_half_step_always_rounds_up(sheets, cfg):
    """Верх 2.975 м у двух окон разной высоты встаёт на одну линию, а не на соседние."""
    found = [_one_window(sheets[0], cfg, y_m=y, h_m=round(2.975 - y, 3))
             for y in (1.05, 2.013, 0.5)]
    assert {round(e.y_m + e.h_m, 6) for e in found} == {3.0}


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
        "greater than 0": seq[:door + 3] + ["0"] + seq[door + 4:],
    }[what]


def _with_parent(seq: list[str], number: str) -> list[str]:
    at = seq.index(Mark.PARENT)
    return seq[:at + 1] + [number] + seq[at + 2:]


@pytest.mark.parametrize("what", [
    "оборвалась", "ждали <wall>", "ждали число", "такого номера в стене нет", "ещё 1 токенов",
    "ждали <answer>", "greater than 0"])
def test_broken_answer_refused_with_reason(sheets, cfg, what):
    """Ответ модели бывает негодным: разбор не чинит его молча, а называет причину."""
    with pytest.raises(TokenError, match=what):
        tokens.decode(_broken(_answer(sheets, cfg), what), _bare(sheets[0]), cfg)


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
