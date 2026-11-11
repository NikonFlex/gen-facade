"""Синтетика «язык» (gf#217): расстановка проёмов `placement = "random"` не зависит от правил
генератора, а грамматика ответа, пределы плана и валидатор — те же, что у `rules`."""

from collections import Counter
from itertools import chain

import pytest
from contours import only_toml

from genfacade import config
from genfacade.datasets.synthetic import batch, build
from genfacade.schema import ContourKind, ElementClass, Mode, OpeningKind, Placement, Source
from genfacade.train import constraints, tokens
from genfacade.validate import errors, validate

SEEDS = range(60)
MODES = (Mode.BLIND, Mode.WITH_OPENINGS)


def _config(tmp_path_factory, placement: Placement) -> config.Config:
    folder = tmp_path_factory.mktemp(f"placement-{placement}")
    (folder / "synthetic.toml").write_text(
        only_toml(ContourKind.RECT) + f'[openings]\nplacement = "{placement}"\n')
    return config.load(folder)


@pytest.fixture(scope="module")
def by_placement(tmp_path_factory):
    """Один и тот же набор seed в обоих режимах расстановки: placement → (настройки, дома). Дом с
    ошибкой валидатора в датасет не идёт (batch.run), поэтому и здесь отброшен."""
    out = {}
    for placement in Placement:
        cfg = _config(tmp_path_factory, placement)
        houses = [build.sample(s, cfg) for s in SEEDS]
        out[placement] = cfg, [h for h in houses if not errors(validate(h.sheet, cfg.checks))]
    return out


def _windows(sheet):
    elements = chain.from_iterable(f.elements for f in sheet.facades)
    return [e for e in elements if e.cls is ElementClass.WINDOW]


def head_line_share(sheet, cfg) -> tuple[int, int]:
    """(окон, чей верх совпал с верхом другого окна того же этажа дома; всего окон): верх — в
    шагах сетки токенов, как его видит модель."""
    by_floor: dict[int, list[int]] = {}
    for w in _windows(sheet):
        by_floor.setdefault(w.floor, []).append(tokens.units(w.y_m + w.h_m, cfg.tokens))
    same = sum(1 for tops in by_floor.values() for t in tops if Counter(tops)[t] > 1)
    return same, sum(len(tops) for tops in by_floor.values())


def _share(houses, cfg) -> float:
    found = [head_line_share(h.sheet, cfg) for h in houses]
    return sum(s for s, _ in found) / sum(n for _, n in found)


def test_default_placement_is_rules(cfg):
    assert cfg.synthetic.openings.placement is Placement.RULES


@pytest.mark.slow
def test_random_windows_do_not_share_head_line_unlike_rules(by_placement):
    """Правила ставят верх окон этажа на одну линию (доля ≈ 1); случайная расстановка — нет:
    остаются только случайные совпадения на сетке."""
    rules = _share(by_placement[Placement.RULES][1], by_placement[Placement.RULES][0])
    rand = _share(by_placement[Placement.RANDOM][1], by_placement[Placement.RANDOM][0])
    assert rules > 0.9
    assert rand < 0.5 and rand < rules / 2


@pytest.mark.slow
def test_answer_grammar_is_same_in_both_placements(by_placement):
    """Ответ в обоих режимах расстановки пишется токенами и разбирается обратно, в обоих режимах
    модели; брака мало — расстановка не ломает дома."""
    for cfg, houses in by_placement.values():
        assert len(houses) >= len(SEEDS) * 0.9
        for h in houses:
            for mode in MODES:
                back = tokens.decode(tokens.answer(h.sheet, mode, cfg), tokens.bare(h.sheet), cfg)
                assert len(_windows(back)) == len(_windows(h.sheet)), h.id


def test_house_has_at_most_allowed_window_types(by_placement):
    """Типоразмер окна — ширина и высота в шагах сетки; у дома их не больше, чем допускает свод
    (window_types) — в обоих режимах расстановки."""
    for cfg, houses in by_placement.values():
        for h in houses:
            sizes = {(tokens.units(w.w_m, cfg.tokens), tokens.units(w.h_m, cfg.tokens))
                     for w in _windows(h.sheet)}
            assert 1 <= len(sizes) <= tokens.window_types(cfg), h.id


def _wall_limits(wall, rules, eps, floors):
    """Окна стены по этажам (x, ширина): не ближе к углу нормы стража, не в запретной зоне и не
    ближе простенка друг к другу; окна во фронтоне (этажа под скатом, gf#321)."""
    corner, between = rules.openings.window_corner_m, rules.openings.between_m
    for floor in {w.floor for w in wall.elements if w.cls is ElementClass.WINDOW} - {floors + 1}:
        row = sorted((w.x_m, w.x_m + w.w_m) for w in wall.elements
                     if w.cls is ElementClass.WINDOW and w.floor == floor)
        assert all(corner - eps <= a and b <= wall.side.length_m - corner + eps for a, b in row)
        assert all(not (z.x0_m + eps < b and a < z.x1_m - eps)
                   for a, b in row for z in wall.side.forbidden)
        assert all(c - b >= between - eps for (_, b), (c, _) in zip(row, row[1:], strict=False))


def test_random_windows_keep_limits_of_plan_and_floor(by_placement):
    """Окна случайной расстановки: пределы стены (`_wall_limits`); целиком в своём этаже под
    перемычкой, не ниже нормы стража."""
    cfg, houses = by_placement[Placement.RANDOM]
    rules = build.with_norms(cfg).synthetic
    lowest = tokens.metres(constraints.norms(cfg).lowest, cfg.tokens)
    eps = cfg.checks.eps_m
    for h in houses:
        levels = h.sheet.spec.floor_levels()
        for f in h.sheet.facades:
            _wall_limits(f, rules, eps, h.sheet.spec.floors)
        for w in (w for w in _windows(h.sheet) if w.floor <= h.sheet.spec.floors):
            assert levels[w.floor - 1] - eps <= w.y_m and w.h_m >= lowest - eps, h.id
            assert w.y_m + w.h_m <= levels[w.floor] - rules.facade.windows.lintel_m + eps, h.id


def test_random_upper_floors_have_their_own_rows(by_placement):
    """У трёх этажей верхние ряды стены — не повтор нижнего и не повтор друг друга; у правил
    третий этаж повторяет второй."""
    def rows(houses, floors):
        out = []
        for h in houses:
            if h.sheet.spec.floors == 3:
                for f in h.sheet.facades:
                    by = {n: sorted((w.x_m, w.w_m) for w in f.elements
                                    if w.cls is ElementClass.WINDOW and w.floor == n)
                          for n in (1, 2, 3)}
                    out.append(by[floors[0]] != by[floors[1]] and bool(by[1]))
        return out

    rand = rows(by_placement[Placement.RANDOM][1], (2, 3))
    rules = rows(by_placement[Placement.RULES][1], (2, 3))
    assert rand and sum(rand) / len(rand) > 0.5
    assert not any(rules)


def test_random_batch_is_marked_with_its_placement(at):
    """Сборка random в папке сборки rules остановлена: дома вышли бы разными."""
    rules, random_ = at("data"), at("data", '[openings]\nplacement = "random"\n')
    batch.run(range(3), rules)
    with pytest.raises(batch.BuildError, match="другими настройками"):
        batch.run(range(5), random_)
    batch.run(range(5), random_, overwrite=True)
    saved = random_.data.paths.samples_dir / Source.SYNTHETIC / batch.BUILD
    assert '"placement": "random"' in saved.read_text()


def test_blind_walls_stay_blind_on_every_floor_when_random(by_placement):
    cfg, houses = by_placement[Placement.RANDOM]
    for h in houses:
        for f in h.sheet.facades:
            plan_windows = [o for o in f.side.openings if o.kind is OpeningKind.WINDOW]
            assert bool(plan_windows) == bool([w for w in f.elements
                                               if w.cls is ElementClass.WINDOW]), h.id
