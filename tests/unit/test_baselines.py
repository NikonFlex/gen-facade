"""Правило GenPlan как базовый подход (gf#141, `evaluation: Базовые подходы`): окна — разрывы
плана, высота одна на дом, в глухом режиме окон нет.
"""

from genfacade.baselines import Baseline, run
from genfacade.metrics import measures
from genfacade.schema import ElementClass, FacadeSheet, Mode, OpeningKind, ZoneRole


def _rule(sheet, cfg, tmp_path) -> FacadeSheet:
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "h.json").write_text(sheet.model_dump_json())
    out = run(Baseline.GENPLAN, tmp_path / "in", cfg, tmp_path / "out")
    return FacadeSheet.model_validate_json((out / "h.json").read_text())


def test_windows_stand_on_plan_gaps(house, cfg, tmp_path):
    ours = _rule(house, cfg, tmp_path)
    for f in ours.facades:
        gaps = sorted((o.x_m, o.width_m) for o in f.side.openings if o.kind is OpeningKind.WINDOW)
        assert sorted((w.x_m, w.w_m) for w in measures.windows(f)) == gaps
    assert any(measures.windows(f) for f in ours.facades)


def test_one_window_height_for_the_house(house, cfg, tmp_path):
    ours = _rule(house, cfg, tmp_path)
    low, high = cfg.baselines.genplan.window
    base, h = ours.spec.floor_levels()[0], ours.spec.floor_heights_m[0]
    boxes = {(round(w.y_m, 6), round(w.h_m, 6)) for f in ours.facades for w in measures.windows(f)}
    assert boxes == {(round(base + low * h, 6), round((high - low) * h, 6))}


def test_blind_mode_has_no_windows_but_keeps_the_entrance(lay_out, cfg, tmp_path):
    ours = _rule(lay_out(Mode.BLIND), cfg, tmp_path)
    elements = [e for f in ours.facades for e in f.elements]
    assert not [e for e in elements if e.cls is ElementClass.WINDOW]
    assert [e for e in elements if e.cls is ElementClass.DOOR]


def test_one_finish_on_the_whole_wall(house, cfg, tmp_path):
    ours = _rule(house, cfg, tmp_path)
    assert all([z.role for z in f.zones] == [ZoneRole.MAIN] for f in ours.facades)
    assert not [e for f in ours.facades for e in f.elements if e.cls is ElementClass.SILL]


def test_plan_door_stays_a_door(house, cfg, tmp_path):
    """Дверь плана (не вход) — дверь, а не окно."""
    k, f = next((k, f) for k, f in enumerate(house.facades) if measures.windows(f))
    gap = next(o for o in f.side.openings if o.kind is OpeningKind.WINDOW)
    side = f.side.model_copy(update={"openings": [
        o.model_copy(update={"kind": OpeningKind.DOOR}) if o is gap else o
        for o in f.side.openings]})
    facades = list(house.facades)
    facades[k] = f.model_copy(update={"side": side})
    ours = _rule(house.model_copy(update={"facades": facades}), cfg, tmp_path).facades[k]
    assert [e.cls for e in ours.elements if e.x_m == gap.x_m] == [ElementClass.DOOR]
