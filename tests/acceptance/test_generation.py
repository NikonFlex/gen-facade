"""Критерии приёмки specs/generation.md для правил шагов 1 и 4 (gf#50).

Критерий «разбор текста с точностью из evaluation.md» — на ручном наборе, этап 2 (gf#13).
"""

from pathlib import Path

import pytest

from genfacade.schema import EPS

ROOT = Path(__file__).parents[2]
PLANS = [ROOT / "materials" / "genplan-plan-example.svg",
         *sorted((ROOT / "tests" / "fixtures" / "genplan").glob("*.svg"))]
TEXTS = ["Two-storey classic house with a gable roof.",
         "Modern villa with a flat roof and panoramic windows.",
         "Small wooden bungalow in Scandinavian style.",
         "Three-story townhouse, hip roof, small windows."]
SEEDS = range(6)


@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.stem)
@pytest.mark.parametrize("text", TEXTS, ids=lambda t: t[:20])
def test_plan_openings_kept_in_place(lay_out, plan, text):
    """Режим с референсами: все проёмы плана на фасаде в тех же положениях."""
    sheet = lay_out(plan, text)
    for f in sheet.facades:
        ground = [e for e in f.elements if e.floor == 1 and e.cls in ("window", "door")]
        for o in f.side.openings:
            same = [e for e in ground
                    if abs(e.x_m - o.x_m) <= EPS and abs(e.w_m - o.width_m) <= EPS]
            assert same, f"сторона {f.side.index}: проём {o} потерян"


@pytest.mark.parametrize("plan", PLANS, ids=lambda p: p.stem)
@pytest.mark.parametrize("seed", SEEDS)
def test_blind_no_window_in_forbidden_zone(lay_out, plan, seed):
    """Режим без референсов: ни одно окно не попадает в запретную зону."""
    sheet = lay_out(plan, TEXTS[seed % len(TEXTS)], mode="blind", seed=seed)
    for f in sheet.facades:
        for w in (e for e in f.elements if e.cls == "window"):
            for z in f.side.forbidden:
                assert w.x_m + w.w_m <= z.x0_m + EPS or w.x_m >= z.x1_m - EPS, \
                    f"сторона {f.side.index}: окно {w.id} в запретной зоне {z}"


@pytest.mark.parametrize("mode", ["with_openings", "blind"])
def test_same_seed_same_result(lay_out, mode):
    runs = [lay_out(PLANS[0], TEXTS[0], mode=mode, seed=3) for _ in range(2)]
    assert runs[0] == runs[1]


def test_seed_changes_blind_layout(lay_out):
    layouts = {lay_out(PLANS[0], TEXTS[0], mode="blind", seed=s).model_dump_json() for s in SEEDS}
    assert len(layouts) > 1
