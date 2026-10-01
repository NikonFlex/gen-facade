"""Критерии приёмки specs/generation.md для шага 4 — пока на стабе модели и простом доме (gf#60).

Для модели (этап 4) — «разбор текста с точностью из evaluation.md», «один seed — один
результат», «в режиме без референсов ни одно окно не в запретной зоне»: стаб текст не читает,
детерминирован и окна не расставляет — отдаёт заготовку простого дома.
"""

import pytest

from genfacade.schema import EPS


def test_plan_openings_kept_in_place(lay_out):
    """Режим с референсами: все проёмы плана на фасаде в тех же положениях."""
    sheet = lay_out()
    for f in sheet.facades:
        ground = [e for e in f.elements if e.floor == 1 and e.cls in ("window", "door")]
        for o in f.side.openings:
            same = [e for e in ground
                    if abs(e.x_m - o.x_m) <= EPS and abs(e.w_m - o.width_m) <= EPS]
            assert same, f"сторона {f.side.index}: проём {o} потерян"


@pytest.mark.parametrize("mode", ["with_openings", "blind"])
def test_same_input_same_result(lay_out, mode):
    """Стаб детерминирован: seed и случайность появятся с моделью (этап 4)."""
    assert lay_out(mode) == lay_out(mode)
