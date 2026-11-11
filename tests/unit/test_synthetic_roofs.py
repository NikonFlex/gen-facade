"""Составные крыши синтетики: крыша пристройки и щипец над входом (gf#431,
`facade: Крыша над частями дома`, `facade: Щипец над карнизной стеной`)."""

import pytest

from genfacade import roof
from genfacade.config import Config
from genfacade.datasets.synthetic import build, roofs
from genfacade.parts import main_wing
from genfacade.schema import FacadeSheet, Mode, OpeningKind, RoofKind
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
    """Щипец, что мог бы встать над входом дома без своего: самый широкий из допустимых."""
    rules = cfg.synthetic.spec.composite
    bare = sheet.model_copy(update={"wall_gables": []})
    house = roof.roofs(bare)
    if sheet.spec.roof.kind is not RoofKind.GABLE or house is None:
        return None
    return roofs._over_entrance(bare, house, rules.wall_gable_share[1],
                                rules.wall_gable_pitch_deg[0], rules)


def test_share_of_own_part_roofs_follows_config(sheets, cfg):
    suited = [s for s in sheets if _winged(s)]
    own = [s for s in suited if s.roofs and any(r != s.spec.roof for r in s.roofs)]
    assert len(suited) > 50
    assert abs(len(own) / len(suited) - cfg.synthetic.spec.composite.part_p) <= SHARE_TOL


def test_share_of_wall_gables_follows_config(sheets, cfg):
    suited = [s for s in sheets if _entrance_gable(s, cfg) is not None]
    gabled = [s for s in sheets if s.wall_gables]
    assert len(suited) > 30
    assert all(_entrance_gable(s, cfg) is not None for s in gabled)  # щипцы — только где можно
    assert abs(len(gabled) / len(suited) - cfg.synthetic.spec.composite.wall_gable_p) <= SHARE_TOL


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


def test_main_wing_keeps_house_roof(sheets):
    for s in (s for s in sheets if s.roofs):
        assert s.roofs[main_wing(s.wings)] == s.spec.roof


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


def test_corpus_is_unchanged_by_roofs(cfg):
    """При нулевых долях и при умолчаниях стены и условие модели одинаковы: крыши — после
    раскладки и со своим потоком случайных чисел."""
    off = composite(cfg, part_p=0.0, wall_gable_p=0.0)
    changed = 0
    for seed in SAME_SEEDS:
        a, b = build.sample(seed, off).sheet, build.sample(seed, cfg).sheet
        assert not a.roofs and not a.wall_gables
        changed += bool(b.roofs or b.wall_gables)
        assert [f.elements for f in a.facades] == [f.elements for f in b.facades]
        assert [f.zones for f in a.facades] == [f.zones for f in b.facades]
        assert a.spec == b.spec
        assert all(tokens.encode(a, m, cfg) == tokens.encode(b, m, cfg) for m in Mode)
    assert changed > 3  # тест не пустой: у умолчаний составные крыши есть
