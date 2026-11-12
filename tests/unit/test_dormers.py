"""Слуховые окна (gf#457): `facade: Слуховое окно`, `generation: Слуховые окна по словам текста`."""

import math
from xml.etree import ElementTree

import numpy
import pytest
import shapely
import vocab

from genfacade import config, dormers, roof
from genfacade.datasets import manual, rect_house
from genfacade.models import stub
from genfacade.render import ifc
from genfacade.render.house3d import house_3d
from genfacade.render.svg import sheet_svg
from genfacade.schema import EPS, Dormer, DormerRoof, Facing, Roof, RoofKind, Source

CFG = config.load()
TEXT = "A one-and-a-half storey house with dormers. Gable roof."


def house(dorms, pitch=45.0, kind=RoofKind.GABLE):
    """Дом 10 × 6 м, карниз 3,0 м; при 45° конёк 6,0 м."""
    spec = stub.spec_model("", CFG.models.spec)
    spec = spec.model_copy(update={
        "eaves_m": 3.0, "floors": 1, "floor_heights_m": [3.0 - spec.plinth_m],
        "roof": Roof(kind=kind, pitch_deg=pitch, overhang_m=0.5, material=spec.roof.material),
        "dormers": dorms})
    fp = rect_house.rectangle(numpy.array((0.0, 0.0)), numpy.array((10.0, 6.0)), 0.4)
    return rect_house.assemble(spec, fp, [(k, []) for k in range(4)], Source.MANUAL)[1]


def plan_area(faces):
    return sum(shapely.Polygon([(x, y) for x, y, _ in f]).area for f in faces)


def south(kind=DormerRoof.GABLE):
    return [Dormer(facing=Facing.Y_MINUS, at=0.5, width_m=1.6, roof=kind)]


def test_gable_dormer_numbers():
    """Сценарий «Двускатный дормер»: лицо 3,3–4,2 м в 0,3 м от стены, конёк 5,0 м."""
    (b,) = dormers.build(house(south()), CFG)
    face = next(s for s in b.solids if s.part is dormers.Part.WALL).points
    assert min(p[2] for p in face) == pytest.approx(3.3)
    assert max(p[2] for p in face) == pytest.approx(5.0)  # со щипцом
    assert {round(p[2], 3) for p in face if p[2] < 4.5} == {3.3, 4.2}
    assert {round(p[1], 3) for p in face} == {-5.7}  # стена на y = −6
    assert b.profile.top == pytest.approx(4.2)
    assert b.profile.z_top == pytest.approx(5.0)
    assert b.profile.z_top < 6.0 - CFG.dormer.below_ridge_m


def test_shed_dormer():
    (b,) = dormers.build(house(south(DormerRoof.SHED)), CFG)
    tilt = math.tan(math.radians(CFG.dormer.shed_pitch_deg))
    d = b.profile.d_top
    assert b.profile.z_top == pytest.approx(3.0 + d)  # на скате дома 45°
    assert b.profile.z_top == pytest.approx(4.2 + tilt * (d - 0.3))


@pytest.mark.parametrize("sheet", [house(south(), pitch=20.0), house(south(), 0.0, RoofKind.FLAT)],
                         ids=["pitch20", "flat"])
def test_no_dormer(sheet):
    assert dormers.build(sheet, CFG) == []


def test_too_wide_for_slope():
    wide = [Dormer(facing=Facing.Y_MINUS, at=0.95, width_m=1.6, roof=DormerRoof.GABLE)]
    assert dormers.build(house(wide), CFG) == []


def test_roof_cut_under_dormer():
    sheet = house(south())
    (b,) = dormers.build(sheet, CFG)
    faces = roof.house_faces(roof.roofs(sheet))
    cut = dormers.cut(faces, [b])
    assert plan_area(faces) - plan_area(cut) == pytest.approx(b.hole().area)


def test_sheet_3d_ifc_have_dormer():
    sheet = house(south())
    svg = sheet_svg(sheet, CFG)
    assert 'class="dormer-glass"' in svg and 'class="dormer-wall"' in svg
    assert 'class="dormer-glass"' not in sheet_svg(house([]), CFG)
    assert len(house_3d(sheet, CFG)["roof"]["windows"]) == 1
    text, base = ifc.counts(ifc.house_ifc(sheet, CFG)), ifc.counts(ifc.house_ifc(house([]), CFG))
    assert text["IFCWALL"] - base["IFCWALL"] == 3  # лицо и две щёчки
    assert text["IFCWINDOW"] - base.get("IFCWINDOW", 0) == 1
    assert text["IFCSLAB"] - base["IFCSLAB"] == 5  # вырез: 4 клетки вместо 1 + 2 ската крыши − 1


def test_stub_by_word():
    assert [d.facing for d in stub.spec_model(TEXT, CFG.models.spec).dormers] == [
        Facing.Y_MINUS, Facing.Y_PLUS]
    assert stub.spec_model("A house. Gable roof.", CFG.models.spec).dormers == []
    assert stub.spec_model("house without dormers", CFG.models.spec).dormers == []
    assert stub.spec_model("flat roof house with dormers", CFG.models.spec).dormers == []


def test_on_eaves_follows_plan():
    sheet = house(south())
    two = dormers.on_eaves(sheet.model_copy(update={"spec": sheet.spec.model_copy(
        update={"dormers": [Dormer(facing=Facing.X_PLUS, at=0.5, width_m=1.6,
                                   roof=DormerRoof.GABLE)]})}))
    assert {d.facing for d in two.spec.dormers} == {Facing.Y_MINUS, Facing.Y_PLUS}


def test_model_vocabulary_unchanged():
    assert vocab.fingerprint(CFG) == vocab.FROZEN


def test_markup_gives_dormer(tmp_path):
    m = manual.read(CFG.data.manual.paths.markup_dir / "freefarmhouse" / "ffh-june.toml")
    sample, _ = manual.house(m, CFG.data.manual)
    assert [(d.roof, d.facing) for d in sample.sheet.spec.dormers] == [
        (DormerRoof.SHED, Facing.X_PLUS), (DormerRoof.SHED, Facing.X_MINUS)]
    assert all(d.at == pytest.approx(0.5, abs=0.01) for d in sample.sheet.spec.dormers)


def test_from_view_outside_wall_is_none():
    sheet = house([])
    side = next(k for k, f in enumerate(sheet.facades) if f.side.orientation == (0.0, -1.0))
    assert dormers.from_view(sheet, side, (4.2, 5.8), DormerRoof.GABLE).at == pytest.approx(0.5)
    assert dormers.from_view(sheet, side, (9.5, 11.1), DormerRoof.GABLE) is None


def test_gentle_slope_refused_by_pitch_alone(monkeypatch):
    """Отказ по уклону — отдельное правило: остальные проверки (конёк, основание) сняты."""
    relaxed = CFG.model_copy(update={"dormer": CFG.dormer.model_copy(
        update={"below_ridge_m": -10.0})})
    monkeypatch.setattr(dormers, "_on_own_slope", lambda b: True)
    assert len(dormers.build(house(south(), pitch=30.0), relaxed)) == 1
    assert dormers.build(house(south(), pitch=20.0), relaxed) == []


def test_dormer_only_on_views_it_belongs_to():
    """mae: окно дормера — только на виде его карнизной стены (мудрум, сторона 6); на других
    видах куски дормера стоят на видимой кровле и не выходят за край стены."""
    m = manual.read(CFG.data.manual.paths.markup_dir / "freefarmhouse" / "ffh-mae.toml")
    sheet = manual.house(m, CFG.data.manual)[0].sheet
    root = ElementTree.fromstring(sheet_svg(sheet, CFG))
    groups = {int(g.get("data-side")): g for g in root.findall("{*}g[@class='facade']")}
    glass = {k for k, g in groups.items() if g.findall("{*}polygon[@class='dormer-glass']")}
    assert glass == {6}
    for k, g in groups.items():
        length = sheet.facades[k].side.length_m
        for p in g.findall("{*}polygon"):
            if p.get("class", "").startswith("dormer"):
                xs = [float(pt.split(",")[0]) for pt in p.get("points").split()]
                assert min(xs) >= -EPS and max(xs) <= length + EPS, (k, p.get("class"), xs)
