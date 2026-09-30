"""Критерии приёмки specs/generation.md для правила шага 4 — на простом доме (gf#58).

Критерии «разбор текста с точностью из evaluation.md» и «один seed — один результат» —
для модели (этап 4): до неё текст не читается, а правило детерминировано.
"""

import pytest

from genfacade.schema import EPS

LEAF = '<rect x="800" y="495" width="5" height="90" fill="#000000" />'
# Внутренние стены упираются в стены простого дома — запретные зоны на трёх сторонах.
# Слева зона на 3.0–3.1 м — там, где без обхода встало бы окно (по центру отрезка 0.8–4.2 м).
INNER = ('<rect x="500" y="115" width="10" height="285" fill="#000000" />'
         '<rect x="115" y="250" width="285" height="10" fill="#000000" />'
         '<rect x="115" y="400" width="285" height="10" fill="#000000" />'
         '<rect x="450" y="300" width="10" height="285" fill="#000000" />')


@pytest.mark.parametrize("roof", ["flat", "gable", "hip"])
def test_plan_openings_kept_in_place(lay_out, roof):
    """Режим с референсами: все проёмы плана на фасаде в тех же положениях."""
    sheet = lay_out(roof=roof)
    for f in sheet.facades:
        ground = [e for e in f.elements if e.floor == 1 and e.cls in ("window", "door")]
        for o in f.side.openings:
            same = [e for e in ground
                    if abs(e.x_m - o.x_m) <= EPS and abs(e.w_m - o.width_m) <= EPS]
            assert same, f"сторона {f.side.index}: проём {o} потерян"


def test_blind_no_window_in_forbidden_zone(lay_out, simple_svg):
    """Режим без референсов: ни одно окно не попадает в запретную зону."""
    sheet = lay_out("blind", svg=simple_svg((LEAF, INNER + LEAF)))
    assert sum(len(f.side.forbidden) for f in sheet.facades) == 4
    for f in sheet.facades:
        for w in (e for e in f.elements if e.cls == "window"):
            for z in f.side.forbidden:
                assert w.x_m + w.w_m <= z.x0_m + EPS or w.x_m >= z.x1_m - EPS, \
                    f"сторона {f.side.index}: окно {w.id} в запретной зоне {z}"


@pytest.mark.parametrize("mode", ["with_openings", "blind"])
def test_same_input_same_result(lay_out, mode):
    """Правило детерминировано: seed и случайность появятся с моделью (этап 4)."""
    assert lay_out(mode) == lay_out(mode)
