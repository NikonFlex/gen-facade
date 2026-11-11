"""Непрямоугольные синтетические дома, ступень 3: Г, Т, П, пристройка, эркер
(`data: Ступени данных`, gf#333)."""

import pytest
from contours import only

from genfacade.datasets.synthetic import build, contour, plan
from genfacade.schema import ContourKind, Mode, OpeningKind
from genfacade.train import tokens
from genfacade.validate import errors, validate

SEEDS = range(24)
# Сколько сторон нарисовано: у Г их 6, у остальных видов — 8 (вырез или выступ добавляют 4 угла).
SIDES = {ContourKind.L: 6, ContourKind.T: 8, ContourKind.U: 8, ContourKind.ANNEX: 8,
         ContourKind.BAY: 8}


@pytest.fixture(scope="module")
def houses(cfg):
    return {k: [build.sample(s, only(cfg, k)) for s in SEEDS] for k in ContourKind}


@pytest.mark.slow
@pytest.mark.parametrize("kind", list(SIDES))
def test_step2_reads_as_many_sides_as_drawn(houses, kind):
    """Препроцессор читает у Г, Т, П, пристройки и эркера столько сторон, сколько нарисовано."""
    assert {len(h.plan.sides) for h in houses[kind]} == {SIDES[kind]}


@pytest.mark.parametrize("kind", list(ContourKind))
def test_plan_scale_is_one_centimetre_and_one_entrance(houses, kind):
    """Вход узнан верно — дверь 90 px, масштаб 0,01 м/px, вход один: перегородка, продолжающая
    стену выреза, лежит в её полосе, и между ними нет ложного разрыва, который шаг 2 принял бы
    за вход."""
    for h in houses[kind]:
        assert h.plan.scale_m_per_px == pytest.approx(0.01), h.id
        assert sum(s.has_entrance for s in h.plan.sides) == 1, h.id


def test_rect_stays_four_sided(houses):
    assert {len(h.plan.sides) for h in houses[ContourKind.RECT]} == {4}


@pytest.mark.parametrize("kind", list(SIDES))
def test_windows_keep_off_every_corner_and_partition(houses, cfg, kind):
    """Окно не ближе нормы к углу стороны — выпуклому и входящему — и не в запретной зоне у
    перегородки, упирающейся в стену."""
    corner = build.with_norms(cfg).synthetic.openings.window_corner_m
    seen = 0
    for h in houses[kind]:
        for side in h.plan.sides:
            for o in (o for o in side.openings if o.kind is OpeningKind.WINDOW):
                seen += 1
                assert o.x_m >= corner - 0.02
                assert side.length_m - (o.x_m + o.width_m) >= corner - 0.02
                assert not any(z.x0_m < o.x_m + o.width_m and o.x_m < z.x1_m
                               for z in side.forbidden)
    assert seen > 0


@pytest.mark.parametrize("kind", list(ContourKind))
@pytest.mark.parametrize("mode", [Mode.BLIND, Mode.WITH_OPENINGS])
def test_house_record_decodes_back(houses, cfg, kind, mode):
    """Запись дома токенами разбирается обратно в тот же дом: записанный вновь — те же токены."""
    for h in houses[kind][:8]:
        written = tokens.answer(h.sheet, mode, cfg)
        back = tokens.decode(written, tokens.bare(h.sheet), cfg)
        assert tokens.answer(back, mode, cfg) == written


@pytest.mark.parametrize("kind", list(ContourKind))
def test_houses_pass_validator(houses, cfg, kind):
    """У домов любого контура нет ошибок валидатора (их батч отбраковывает); предупреждение —
    только о скатной крыше над непрямоугольным контуром (gf#320)."""
    found = [v for h in houses[kind] for v in validate(h.sheet, cfg.checks)]
    assert not errors(found)
    assert all("крыша" in v.message for v in found)


def test_kinds_follow_weights_and_seed(cfg):
    """Вид дома — по seed и весам: те же настройки — те же виды, доля rect — по его весу."""
    syn = cfg.synthetic
    picked = [contour.pick(s, syn) for s in range(400)]
    assert picked == [contour.pick(s, syn) for s in range(400)]
    weights = syn.contours.weights
    share = picked.count(ContourKind.RECT) / len(picked)
    assert abs(share - weights[ContourKind.RECT] / sum(weights.values())) < 0.08
    assert set(picked) == {k for k, w in weights.items() if w > 0}


def test_rect_only_matches_plain_rectangles(cfg):
    """Доля непрямоугольных 0 — дома те же, что давал прямоугольный генератор: план совпадает с
    plan.draft по тому же seed."""
    syn = build.with_norms(only(cfg, ContourKind.RECT)).synthetic
    for s in SEEDS:
        assert contour.draft(s, syn) == plan.draft(s, syn)
