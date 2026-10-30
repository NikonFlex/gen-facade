"""Синтетические дома ступени 1: план в формате GenPlan и правила генератора
(`data: Синтетика своим генератором`)."""

import json
import re

import pytest
from simple_house import SIMPLE

from genfacade import cli, config
from genfacade.datasets import genplan_writer, store
from genfacade.datasets.genplan_writer import Hole, Opening, PlanDraft, Run
from genfacade.datasets.synthetic import build, sizes
from genfacade.datasets.synthetic.plan import draft
from genfacade.plan import genplan_svg
from genfacade.plan.gaps import Axis
from genfacade.plan.preprocess import ENTRANCE_WIDTH_M
from genfacade.schema import OpeningKind, Source
from genfacade.train import tokens

SEEDS = range(60)
# Стороны примера GenPlan (materials/genplan-plan-example.svg, вне git) после препроцессора, м.
GENPLAN_SIDES_M = (4.23, 5.47)
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
    for seed, (sketch, house) in zip(SEEDS, houses, strict=True):
        size = sizes.pick(seed, cfg.synthetic)
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


def test_house_sizes_cover_genplan_sides(cfg):
    """Длина стороны в условии модели — число шагов сетки токенов, и каждое такое число модель
    учит по синтетике: длину, которой там не было, она не читает и раскладывает стену другой
    длины (gf#153, пример GenPlan: стороны 85 и 109 шагов, а в синтетике были 100…280 через 10)."""
    house = cfg.synthetic.sizes.genplan  # профиль «как GenPlan» (gf#186)
    step = round(cfg.synthetic.house.grid_m / cfg.tokens.grid_m)

    def reachable(span: tuple[float, float]) -> range:
        return range(tokens.units(span[0], cfg.tokens), tokens.units(span[1], cfg.tokens) + 1,
                     step)

    short, long_ = (tokens.units(m, cfg.tokens) for m in GENPLAN_SIDES_M)
    assert short in reachable(house.depth_m) and long_ in reachable(house.width_m)


def test_openings_keep_clear_of_corners_partitions_and_each_other(houses, cfg):
    """Отступ от угла и простенок — профиля размеров дома (у «как реальные» теснее, gf#186)."""
    for seed, (_, house) in zip(SEEDS, houses, strict=True):
        rules = sizes.rules(cfg.synthetic, sizes.pick(seed, cfg.synthetic)).openings
        for side in house.plan.sides:
            spans = sorted((o.x_m, o.x_m + o.width_m) for o in side.openings)
            blocked = [(0.0, 0.0), *((z.x0_m, z.x1_m) for z in side.forbidden),
                       (side.length_m, side.length_m)]
            for a, b in zip(spans, spans[1:], strict=False):
                assert b[0] - a[1] >= rules.between_m - 1e-6, house.id
            for x0, x1 in spans:
                near = min(max(x0 - z1, z0 - x1) for z0, z1 in blocked)
                assert near >= rules.corner_clear_m - 1e-6, (house.id, side.index)


def test_entrance_comes_closer_to_corner_than_windows(houses, cfg):
    """Вход — от corner_clear_m от наружного угла, как у GenPlan (вход примера в 0,519 м от угла),
    окна — от внутренней грани стены: ближе толщины стены к углу подходит только вход (gf#177).
    Отступ — профиля размеров дома (gf#186)."""
    wall, near = cfg.synthetic.house.wall_m, False
    for seed, (_, house) in zip(SEEDS, houses, strict=True):
        clear = sizes.rules(cfg.synthetic, sizes.pick(seed, cfg.synthetic)).openings.corner_clear_m
        for side in house.plan.sides:
            for o in side.openings:
                gap = min(o.x_m, side.length_m - o.x_m - o.width_m)
                least = clear if o.kind is OpeningKind.ENTRANCE else wall + clear
                assert gap >= least - 1e-6, (house.id, o.kind)
                near |= o.kind is OpeningKind.ENTRANCE and gap < wall + clear - 1e-6
    assert near


@pytest.fixture(scope="module")
def mixed(cfg):
    """Настройки с профилем «как реальные» (доля 0,3, сетка токенов до 40 м) и дома по ним: в
    основных настройках он выключен (gf#186), но генератор его умеет."""
    sizes_cfg = cfg.synthetic.sizes.model_copy(update={"real_share": 0.3})
    rules = cfg.synthetic.model_copy(update={"sizes": sizes_cfg})
    tok = cfg.tokens.model_copy(update={"max_m": 40.0})
    mix = cfg.model_copy(update={"synthetic": rules, "tokens": tok})
    return mix, [(draft(s, rules), build.sample(s, mix)) for s in SEEDS]


def test_partitions_grow_with_house_length(mixed):
    """Длинный дом делится на больше комнат: перегородок — до длины / room_m (gf#186: у 24 м —
    до 5, у 10 м — до 2, как раньше): иначе окон на его стене меньше, чем у реальных домов."""
    cfg, houses = mixed
    room, counts = cfg.synthetic.partitions.room_m, []
    for sketch, _ in houses:
        inner = [r for r in sketch.runs if any(o.hole is Hole.PASSAGE for o in r.openings)]
        assert len(inner) <= sketch.width_m // room, sketch
        counts.append((sketch.width_m, len(inner)))
    assert any(w > 14 for w, _ in counts) and any(n > 2 for _, n in counts)


def test_genplan_profile_only_by_default(houses, cfg):
    """В основных настройках все дома — «как GenPlan»: словарь модели — сетка до 20 м (gf#186)."""
    assert cfg.synthetic.sizes.real_share == 0
    assert all(sizes.pick(s, cfg.synthetic) is cfg.synthetic.sizes.genplan for s in SEEDS)
    assert max(sketch.width_m for sketch, _ in houses) <= cfg.synthetic.sizes.genplan.width_m[1]
    # ширины окна — из ряда (gf#211), и ряд — в пределах профиля: самое узкое окно берёт страж
    gp = cfg.synthetic.sizes.genplan
    used = {o.width_m for sketch, _ in houses for o in _holes(sketch, Hole.WINDOW)}
    assert used == set(gp.window_widths_m)
    assert gp.window_width_m[0] == min(used) and max(used) <= gp.window_width_m[1]


def test_house_sizes_follow_their_profile(mixed):
    """Профиль размеров по seed (gf#186): «как GenPlan» — прежние стороны и ряд ширин окна, «как
    реальные» — стороны до 24 м и ширина окна на сетке; бывают оба, реальных — около real_share."""
    cfg, houses = mixed
    mix, real, tight = cfg.synthetic.sizes, 0, False
    for seed, (sketch, house) in zip(SEEDS, houses, strict=True):
        size = sizes.pick(seed, cfg.synthetic)
        real += size is mix.real
        assert size.width_m[0] - 1e-6 <= sketch.width_m <= size.width_m[1] + 1e-6
        allowed = sizes.window_widths(size)
        assert all(o.width_m in allowed for o in _holes(sketch, Hole.WINDOW)), seed
        if size is mix.real:  # у реальных домов проёмы теснее, чем позволяет [openings]
            for side in house.plan.sides:
                spans = sorted((o.x_m, o.x_m + o.width_m) for o in side.openings)
                tight = tight or any(b[0] - a[1] < cfg.synthetic.openings.between_m - 1e-6
                                     for a, b in zip(spans, spans[1:], strict=False))
    assert 0 < real < len(houses) and tight


def test_blind_walls_are_made_on_purpose(houses):
    """Глухие стены есть, но не все: у каждого дома хотя бы одно окно
    (`data: Глухие стены в синтетике`)."""
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
    with pytest.raises(SystemExit, match="сборка остановлена"):  # те же дома другой сборкой
        (tmp_path / "synthetic.toml").write_text("[house]\nwall_m = 0.2\n")
        cli.main(["-c", str(tmp_path), "synth", "-n", "3"])
