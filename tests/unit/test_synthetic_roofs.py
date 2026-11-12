"""Составные крыши синтетики: крыша пристройки и щипец над входом (gf#431,
`facade: Крыша над частями дома`, `facade: Щипец над карнизной стеной`)."""

import pytest

from genfacade import entrance_gable, roof
from genfacade.config import Config
from genfacade.datasets.synthetic import build
from genfacade.part_roofs import wing_eaves
from genfacade.parts import main_wing
from genfacade.schema import ElementClass, FacadeSheet, Mode, OpeningKind, RoofKind
from genfacade.train import tokens

SEEDS = range(300)
SHARE_TOL = 0.1  # допуск доли от настройки: на сотне домов разброс выборки около 0,05
SAME_SEEDS = range(40)


def composite(cfg: Config, **update) -> Config:
    """Настройки с правкой составных крыш."""
    syn = cfg.synthetic
    rules = syn.spec.composite.model_copy(update=update)
    spec = syn.spec.model_copy(update={"composite": rules})
    return cfg.model_copy(update={"synthetic": syn.model_copy(update={"spec": spec})})


@pytest.fixture(scope="module")
def sheets(cfg) -> list[FacadeSheet]:
    return [build.sample(seed, cfg).sheet for seed in SEEDS]


def _winged(sheet: FacadeSheet) -> bool:
    return sheet.spec.roof.kind is not RoofKind.FLAT and len(sheet.wings) >= 2


def _entrance_gable(sheet: FacadeSheet, cfg: Config):
    """Щипец, что мог бы встать над входом дома без своего: самый широкий из допустимых и такой,
    что крыша его строит (у части, чей скат от этой стены не поднимается, щипца нет)."""
    rules = cfg.synthetic.spec.composite
    bare = sheet.model_copy(update={"wall_gables": []})
    house = roof.roofs(bare)
    if sheet.spec.roof.kind is not RoofKind.GABLE or house is None:
        return None
    found = entrance_gable.over_entrance(bare, house, rules.wall_gable_share[1],
                                         rules.wall_gable_pitch_deg[0], rules.wall_gable_min_m)
    if found is None:
        return None
    built = roof.roofs(bare.model_copy(update={"wall_gables": [found]}))
    return found if len(built.parts) == len(house.parts) + 1 else None


def _own(sheet: FacadeSheet) -> bool:
    return bool(sheet.roofs) and any(r != sheet.spec.roof for r in sheet.roofs)


@pytest.mark.slow
def test_share_of_own_part_roofs_follows_config(sheets, cfg):
    """Доля среди домов, где пристройка может встать ниже главного: такие дома — при вероятности 1
    (тот же seed — тот же жребий уклона)."""
    always = composite(cfg, part_p=1.0)
    suited = {seed for seed in SEEDS if _own(build.sample(seed, always).sheet)}
    own = {seed for seed, s in zip(SEEDS, sheets, strict=True) if _own(s)}
    assert len(suited) > 30
    assert own <= suited  # своя крыша — только где пристройка ниже главного
    assert abs(len(own) / len(suited) - cfg.synthetic.spec.composite.part_p) <= SHARE_TOL


@pytest.mark.slow
def test_own_roof_only_on_wings_lower_than_main(sheets):
    """Решение 108: своя односкатная — у крыла ниже главного по карнизу; крылья одной высоты —
    под крышей дома, у синтетики и у настоящих домов."""
    seen = 0
    for s in (s for s in sheets if _winged(s)):
        eaves, main = wing_eaves(s), main_wing(s.wings)
        for i, own in enumerate(s.roofs or [s.spec.roof] * len(s.wings)):
            lower = eaves[i] < eaves[main] - 1e-6
            assert (own != s.spec.roof) <= lower
            seen += own != s.spec.roof
    assert seen > 20


@pytest.mark.slow
def test_share_of_wall_gables_follows_config(sheets, cfg):
    """Доля щипцов среди домов, где он встаёт: такие дома — щипец при вероятности 1 (тот же seed —
    те же ширина и уклон щипца: жребии тянутся всегда)."""
    always = composite(cfg, wall_gable_p=1.0)
    suited = {seed for seed in SEEDS if build.sample(seed, always).sheet.wall_gables}
    gabled = {seed for seed, s in zip(SEEDS, sheets, strict=True) if s.wall_gables}
    assert len(suited) > 30
    assert gabled <= suited  # щипцы — только где можно
    assert abs(len(gabled) / len(suited) - cfg.synthetic.spec.composite.wall_gable_p) <= SHARE_TOL


@pytest.mark.slow
def test_extension_is_shed_sloping_away_from_main_wing(sheets):
    """Скат пристройки поднимается от внешней стены к главному крылу: на общей стене кровля выше,
    чем на противоположной."""
    seen = 0
    for s in (s for s in sheets if s.roofs):
        house, main = roof.roofs(s), main_wing(s.wings)
        for k, own in enumerate(s.roofs):
            if own == s.spec.roof:  # крыша дома, а не пристройки
                continue
            seen += 1
            line, w, m = house.parts[k], s.wings[k], s.wings[main]
            (slope,) = line.slopes
            to_main = ((m.x0_m + m.x1_m) / 2 - (w.x0_m + w.x1_m) / 2,
                       (m.y0_m + m.y1_m) / 2 - (w.y0_m + w.y1_m) / 2)
            assert slope.inward[0] * to_main[0] + slope.inward[1] * to_main[1] > 0
            assert slope.inward == pytest.approx((-own.down_to.normal[0], -own.down_to.normal[1]))
            assert own.material == s.spec.roof.material
    assert seen > 20


@pytest.mark.slow
def test_main_wing_keeps_house_roof(sheets):
    for s in (s for s in sheets if s.roofs):
        assert s.roofs[main_wing(s.wings)] == s.spec.roof


@pytest.mark.slow
def test_wall_gable_is_over_entrance_inside_its_span(sheets, cfg):
    rules = cfg.synthetic.spec.composite
    seen = 0
    for s in (s for s in sheets if s.wall_gables):
        (g,) = s.wall_gables
        door = next(o for o in s.facades[g.side].side.openings if o.kind is OpeningKind.ENTRANCE)
        span = next(p for p in roof.roofs(s).spans[g.side] if p.x0 <= g.x0_m <= p.x1)
        overhang = roof.roofs(s).parts[span.part].overhang
        assert g.x0_m <= door.x_m + door.width_m / 2 <= g.x1_m
        assert span.x0 + overhang - 1e-6 <= g.x0_m and g.x1_m <= span.x1 - overhang + 1e-6
        assert g.x1_m - g.x0_m >= rules.wall_gable_min_m - 1e-6
        assert len(roof.roofs(s).parts) == len(roof.roofs(
            s.model_copy(update={"wall_gables": []})).parts) + 1
        seen += 1
    assert seen > 3


@pytest.mark.slow
def test_corpus_is_unchanged_by_roofs(cfg):
    """При нулевых долях и при умолчаниях стены и условие модели одинаковы у домов без ступеней:
    крыши — после раскладки и со своим потоком случайных чисел; ступени — только у дома, которому
    выпала пристройка под своей крышей (`roofs.annexed`)."""
    off = composite(cfg, part_p=0.0, wall_gable_p=0.0)
    changed = 0
    for seed in SAME_SEEDS:
        a, b = build.sample(seed, off).sheet, build.sample(seed, cfg).sheet
        assert not a.roofs and not a.wall_gables
        changed += bool(b.roofs or b.wall_gables)
        if any(f.runs for f in b.facades):
            continue
        assert [f.elements for f in a.facades] == [f.elements for f in b.facades]
        assert [f.zones for f in a.facades] == [f.zones for f in b.facades]
        assert a.spec == b.spec
        assert all(tokens.encode(a, m, cfg) == tokens.encode(b, m, cfg) for m in Mode)
    assert changed > 3  # тест не пустой: у умолчаний составные крыши есть


@pytest.mark.slow
def test_annex_house_is_built_in_steps_with_lower_wing(cfg):
    """Дом с пристройкой под своей крышей — со ступенью: нижнее крыло ниже главного на этаж, у него
    односкатная крыша, окна верхних этажей — по участкам (ни одно не выше карниза своей части)."""
    always = composite(cfg, part_p=1.0)
    stepped = [s for s in (build.sample(seed, always).sheet for seed in range(60))
               if any(f.runs for f in s.facades)]
    assert len(stepped) > 5
    for s in stepped:
        assert _own(s)
        for f in s.facades:
            for run in f.runs:
                top = max((e.y_m + e.h_m for e in f.elements
                           if run.x0_m - 1e-6 <= e.x_m and e.x_m + e.w_m <= run.x1_m + 1e-6
                           and e.cls is ElementClass.WINDOW), default=0.0)
                assert top <= run.eaves_m + 1e-6
