"""Синтетические дома ступени 1: план в формате GenPlan и правила генератора (data.md, п. 1)."""

import json
import re

import pytest
from simple_house import SIMPLE

from genfacade import cli, config
from genfacade.datasets import genplan_writer, store
from genfacade.datasets.genplan_writer import Hole, Opening, PlanDraft, Run
from genfacade.datasets.synthetic import build
from genfacade.datasets.synthetic.plan import draft
from genfacade.plan import genplan_svg
from genfacade.plan.gaps import Axis
from genfacade.plan.preprocess import ENTRANCE_WIDTH_M
from genfacade.schema import OpeningKind, Source

SEEDS = range(60)
DOOR = Opening(2.0, ENTRANCE_WIDTH_M, Hole.ENTRANCE)
# Простой дом tests/fixtures/simple_house.svg теми же словами, какими дом описывает генератор.
SIMPLE_DRAFT = PlanDraft(10.0, 5.0, 0.15, (
    Run(Axis.X, 0.0, 0.0, 10.0, (Opening(1.5, 1.2, Hole.WINDOW), Opening(7.0, 0.9, Hole.ENTRANCE))),
    Run(Axis.X, 4.85, 0.0, 10.0, (Opening(5.0, 2.0, Hole.WINDOW),)),
    Run(Axis.Y, 0.0, 0.0, 5.0, (Opening(1.5, 1.0, Hole.WINDOW),)),
    Run(Axis.Y, 9.85, 0.0, 5.0, (Opening(2.0, 1.5, Hole.WINDOW),)),
))


@pytest.fixture(scope="module")
def houses(cfg):
    """Черновик и готовый пример для каждого seed."""
    return [(draft(s, cfg.synthetic), build.sample(s, cfg)) for s in SEEDS]


def _holes(sketch: PlanDraft, hole: Hole) -> list[Opening]:
    return [o for run in sketch.runs for o in run.openings if o.hole is hole]


def test_writer_draws_what_genplan_draws(cfg, preprocess_svg):
    """Простой дом, нарисованный нашим кодом, препроцессор читает так же, как дом от GenPlan."""
    ours = preprocess_svg(genplan_writer.svg(SIMPLE_DRAFT, cfg.synthetic.canvas))
    theirs = preprocess_svg(SIMPLE)
    assert (ours.sides, ours.outline, ours.scale_m_per_px) == (
        theirs.sides, theirs.outline, theirs.scale_m_per_px)
    assert sorted(ours.openings, key=repr) == sorted(theirs.openings, key=repr)


def test_writer_emits_same_primitives_as_genplan(cfg):
    """Те же прямоугольники стен и окон и та же дверь, что в файле GenPlan, — не только разрывы."""
    ours = genplan_svg.parse(genplan_writer.svg(SIMPLE_DRAFT, cfg.synthetic.canvas))
    theirs = genplan_svg.parse(SIMPLE)
    assert (ours.width, ours.height, ours.doors) == (theirs.width, theirs.height, theirs.doors)
    for kind in ("walls", "windows"):
        assert sorted(getattr(ours, kind), key=repr) == sorted(getattr(theirs, kind), key=repr)


@pytest.mark.parametrize("wall", range(4))
def test_entrance_read_on_every_wall(cfg, preprocess_svg, wall):
    """Створка и дуга входа повёрнуты под каждую из четырёх стен — вход находится везде."""
    runs = [Run(r.axis, r.across_m, r.start_m, r.end_m, (DOOR,) if i == wall else ())
            for i, r in enumerate(SIMPLE_DRAFT.runs)]
    svg = genplan_writer.svg(PlanDraft(10.0, 5.0, 0.15, tuple(runs)), cfg.synthetic.canvas)
    plan = preprocess_svg(svg)
    k, pad = cfg.synthetic.canvas.px_per_m, cfg.synthetic.canvas.margin_m
    drawn = [float(v) / k - pad for v in re.findall(r'(?:x|y)="(\d+)"', svg)]
    assert min(drawn) >= 0 and max(drawn) <= 10.0  # створка открыта внутрь дома, не наружу
    [door] = [o for side in plan.sides for o in side.openings]
    assert door.kind is OpeningKind.ENTRANCE and plan.sides[0].has_entrance
    assert door.width_m == pytest.approx(ENTRANCE_WIDTH_M)
    assert plan.sides[0].length_m == pytest.approx(10.0 if wall < 2 else 5.0)


def test_plan_keeps_every_decision_of_draft(houses, cfg):
    """Что решил генератор, то и прочитал препроцессор: размеры, окна, вход, перегородки."""
    size = cfg.synthetic.house
    for sketch, house in houses:
        sides = house.plan.sides
        windows = [o for s in sides for o in s.openings if o.kind is OpeningKind.WINDOW]
        assert sorted(round(s.length_m, 3) for s in sides) == sorted(
            [sketch.width_m, sketch.depth_m] * 2), house.id
        assert size.depth_m[0] <= sketch.depth_m <= sketch.width_m <= size.width_m[1], house.id
        assert sorted(round(o.width_m, 3) for o in windows) == sorted(
            o.width_m for o in _holes(sketch, Hole.WINDOW)), house.id
        assert sides[0].has_entrance and house.plan.scale_m_per_px == pytest.approx(0.01)
        assert sum(len(s.forbidden) for s in sides) == 2 * len(_holes(sketch, Hole.PASSAGE))
        assert house.plan.source is Source.SYNTHETIC and len(house.sheet.facades) == 4


def test_openings_keep_clear_of_corners_partitions_and_each_other(houses, cfg):
    rules = cfg.synthetic.openings
    for _, house in houses:
        for side in house.plan.sides:
            spans = sorted((o.x_m, o.x_m + o.width_m) for o in side.openings)
            blocked = [(0.0, 0.0), *((z.x0_m, z.x1_m) for z in side.forbidden),
                       (side.length_m, side.length_m)]
            for a, b in zip(spans, spans[1:], strict=False):
                assert b[0] - a[1] >= rules.between_m - 1e-6, house.id
            for x0, x1 in spans:
                near = min(max(x0 - z1, z0 - x1) for z0, z1 in blocked)
                assert near >= rules.corner_clear_m - 1e-6, (house.id, side.index)


def test_blind_walls_are_made_on_purpose(houses):
    """Глухие стены есть, но не все: у каждого дома хотя бы одно окно (data.md, правило 1)."""
    walls = [s for _, house in houses for s in house.plan.sides]
    blind = sum(not s.openings for s in walls) / len(walls)
    assert 0.1 < blind < 0.5
    assert all(_holes(sketch, Hole.WINDOW) for sketch, _ in houses)


def test_house_without_windows_is_redrawn(tmp_path):
    """Почти все стены глухие — дом всё равно выходит с окном: раскладка тянется заново."""
    (tmp_path / "synthetic.toml").write_text(
        "[openings]\nblind_long_p = 0.9\nblind_short_p = 0.9\n")
    rules = config.load(tmp_path).synthetic
    assert all(_holes(draft(s, rules), Hole.WINDOW) for s in range(40))


def test_seed_makes_the_house(cfg):
    one = [build.sample(7, cfg) for _ in range(2)]
    assert one[0] == one[1]
    assert len({build.sample(s, cfg).plan.model_dump_json() for s in range(20)}) == 20


def test_synth_command_writes_samples_and_manifest(tmp_path, capsys):
    (tmp_path / "data.toml").write_text(f'[paths]\nsamples_dir = "{tmp_path / "samples"}"\n')
    cli.main(["-c", str(tmp_path), "synth", "-n", "3", "--first-seed", "5"])
    manifest = json.loads(open(capsys.readouterr().out.strip()).read())
    assert store.ids(tmp_path / "samples", Source.SYNTHETIC) == [
        "rect-000005", "rect-000006", "rect-000007"]
    assert (manifest["samples"], manifest["walls"]) == (3, 12)
