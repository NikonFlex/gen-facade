"""Мансардные окна (gf#456, `facade: Мансардное окно`, `generation: Мансардные окна по словам
текста`): ряд окон в плоскости каждого карнизного ската главной части; на листе, в 3D и в IFC."""

import math

import pytest
import vocab
from simple_house import with_side
from test_part_roofs import GABLE, walls
from test_roof import CFG, bare

from genfacade import roof, skylights
from genfacade.models import stub
from genfacade.render.house3d import house_3d
from genfacade.render.ifc import house_ifc
from genfacade.render.parse import parse_sheet_svg
from genfacade.render.svg import sheet_svg, tops
from genfacade.schema import FacadeSheet, HouseSpec, Mode, RoofKind
from genfacade.train import tokens

LOOK = CFG.sheet.skylight
WIDTH, LENGTH = 0.78, 1.18  # размер из сценария спеки — не из конфига: сломанный конфиг заметен


def house(count: int, kind: RoofKind = RoofKind.GABLE, pitch: float | None = None,
          depth: float = 6.0, length: float = 10.0) -> FacadeSheet:
    """Дом length × depth м с мансардными окнами count на скат; уклон pitch — вместо уклона вида."""
    sheet = bare(kind)
    for k, size_ in ((0, length), (1, depth), (2, length), (3, depth)):
        sheet = with_side(sheet, k, side=sheet.facades[k].side.model_copy(
            update={"length_m": size_}))
    roof_ = sheet.spec.roof if pitch is None else sheet.spec.roof.model_copy(
        update={"pitch_deg": pitch})
    spec = sheet.spec.model_copy(update={"skylights": count, "roof": roof_})
    return sheet.model_copy(update={"spec": spec})


def size(ring) -> tuple[float, float]:
    """Ширина (вдоль карниза) и длина по скату четырёхугольника окна."""
    return math.dist(ring[0], ring[1]), math.dist(ring[1], ring[2])


def test_two_windows_on_each_slope():
    """Сценарий «Два окна на скат»: дом 10 × 6 м, 35°, карниз 3,25 м, конёк 5,35 м."""
    sheet = house(2)
    found = skylights.find(sheet, LOOK)
    assert sheet.spec.eaves_m == pytest.approx(3.25)
    assert sorted(s.slope for s in found) == [0, 0, 1, 1]
    for s in found:
        assert size(s.outer) == pytest.approx((WIDTH, LENGTH))
        assert min(z for _, _, z in s.outer) == pytest.approx(4.05)
        assert max(z for _, _, z in s.outer) == pytest.approx(4.05 + LENGTH * math.sin(
            math.radians(35)), abs=1e-6)
        assert max(z for _, _, z in s.outer) == pytest.approx(4.73, abs=0.005)


def test_windows_lie_in_the_slope_plane():
    """Все четыре угла окна — на плоскости ската: высота = карниз + подъём × глубина."""
    sheet = house(2)
    line, _ = roof.main_faces(sheet)
    for s in skylights.find(sheet, LOOK):
        for ring in (s.outer, s.inner):
            assert all(z == pytest.approx(line.height((x, y))) for x, y, z in ring)


def test_frame_is_wider_than_glass_by_frame_width():
    s = skylights.find(house(1), LOOK)[0]
    assert size(s.inner) == pytest.approx((WIDTH - 2 * LOOK.frame_m,
                                           (LENGTH - 2 * LOOK.frame_m)))


def test_fewer_windows_when_they_do_not_fit():
    """Просят 30 — встаёт, сколько помещается: промежуток 0,1 м, от торцов кровли не ближе 0,5 м."""
    found = skylights.find(house(30), LOOK)
    per_slope = {n: [s for s in found if s.slope == n] for n in (0, 1)}
    assert all(1 < len(row) < 30 for row in per_slope.values())
    row = sorted(per_slope[0], key=lambda s: s.outer[0][0])
    gaps = [abs(b.outer[1][0] - a.outer[0][0]) for a, b in zip(row, row[1:], strict=False)]
    assert all(g == pytest.approx(0.1) for g in gaps)
    # кровля вдоль карниза: дом 10 м и фронтонный свес с каждого торца; отступ 0,5 м от торцов
    span = len(row) * WIDTH + (len(row) - 1) * 0.1
    assert span <= 10 + 2 * 0.2 - 2 * 0.5 + 1e-6 < span + WIDTH + 0.1


def test_no_windows_on_a_shallow_roof():
    """Уклон 10° — положе 15°: окон нет, хоть скат и велик (поместились бы); ровно 15° — есть."""
    wide = {"depth": 24.0, "length": 30.0}
    assert skylights.find(house(2, pitch=10.0, **wide), LOOK) == []
    assert skylights.find(house(2, pitch=15.0, **wide), LOOK)
    assert skylights.find(house(2, pitch=15.0, depth=12.0, length=14.0), LOOK)


def test_no_windows_on_a_flat_roof_or_with_zero_count():
    assert skylights.find(house(2, RoofKind.FLAT), LOOK) == []
    assert skylights.find(house(0), LOOK) == []


def test_no_window_where_the_top_edge_comes_closer_than_ridge_margin():
    """Дом глубиной 4 м при 35°: конёк на 3,25 + 2 · tg 35° ≈ 4,65 м, верх окна 4,73 + запас 0,2
    по скату — выше."""
    assert skylights.find(house(2, depth=4.0), LOOK) == []


def test_hip_roof_puts_windows_on_the_slopes_where_they_fit():
    """Вальмовая 10 × 6: окна встают на длинные скаты (у каждого карнизного ската — свой ряд)."""
    found = skylights.find(house(2, RoofKind.HIP, depth=6.0), LOOK)
    assert len({s.slope for s in found}) >= 2


def test_windows_stand_on_the_main_part_of_a_house_of_two_heights():
    """Г-дом: главная часть — карниз 6,0 м, крыло ниже (3,25 м, односкатная) окон не получает."""
    sheet = walls(GABLE)
    steep = sheet.spec.roof.model_copy(update={"pitch_deg": 50.0})
    sheet = sheet.model_copy(update={
        "spec": sheet.spec.model_copy(update={"skylights": 2, "roof": steep}),
        "roofs": [steep, sheet.roofs[1]]})
    found = skylights.find(sheet, LOOK)
    assert len(found) == 4
    assert min(z for s in found for _, _, z in s.outer) == pytest.approx(6.0 + LOOK.sill_m)


# ——— стаб шага 1 ———


@pytest.mark.parametrize(("text", "count"), [
    ("A house with skylights. Gable roof.", 2),
    ("Дом с мансардными окнами. Двускатная крыша.", 2),
    ("A house with roof windows. Gable roof.", 2),
    ("A house. Gable roof.", 0),
    ("A house without skylights. Gable roof.", 0),
    ("A house with skylights. Flat roof.", 0),
])
def test_stub_puts_skylights_by_words(text, count):
    assert stub.spec_model(text, CFG.models.spec).skylights == count


def test_old_json_without_the_field_is_valid():
    data = stub.spec_model("A house.", CFG.models.spec).model_dump(mode="json")
    del data["skylights"]
    assert HouseSpec.model_validate(data).skylights == 0
    with pytest.raises(ValueError, match="skylights"):
        HouseSpec.model_validate(data | {"skylights": -1})


# ——— лист, 3D, IFC ———


def test_sheet_draws_windows_on_eave_walls_only():
    """На видах карнизных стен — рамка и стекло проекцией (ширина 0,78 м, высота 1,18 · sin 35°),
    на фронтонных — ничего; элементы листа для разбора те же."""
    sheet = house(2)
    svg = sheet_svg(sheet, CFG)
    assert svg.count('class="skylight"') == 4 and svg.count('class="skylight-glass"') == 4
    bare_svg = sheet_svg(house(0), CFG)
    assert 'class="skylight"' not in bare_svg
    assert parse_sheet_svg(svg) == parse_sheet_svg(bare_svg)


def test_sheet_projection_size():
    """Окно на виде: ширина 0,78 м, высота 1,18 · sin 35° — скат виден под углом."""
    top = next(t for t in tops(house(1), CFG) if t.skylights)
    xs, ys = [x for x, _ in top.skylights[0][0]], [y for _, y in top.skylights[0][0]]
    assert max(xs) - min(xs) == pytest.approx(WIDTH)
    assert max(ys) - min(ys) == pytest.approx(LENGTH * math.sin(math.radians(35)))


def test_house_3d_has_frames_and_glass_on_top_of_the_roof():
    sheet = house(2)
    data = house_3d(sheet, CFG)["roof"]
    assert len(data["skylights"]) == len(data["skylight_frames"]) == 4
    line, _ = roof.main_faces(sheet)
    lift = data["thickness_m"] + LOOK.lift_m
    for ring in data["skylight_frames"]:
        assert all(z == pytest.approx(line.height((x, y)) + lift) for x, y, z in ring)
    assert house_3d(house(0), CFG)["roof"]["skylights"] == []


def test_ifc_has_skylight_windows():
    """В IFC — IfcWindow вида SKYLIGHT по числу окон; без окон — ни одного."""
    ifc = house_ifc(house(2), CFG)
    skylight = [ln for ln in ifc.splitlines() if "IFCWINDOW(" in ln and ".SKYLIGHT." in ln]
    assert len(skylight) == 4
    assert all("Мансардное окно" in ln or "\\X2\\" in ln for ln in skylight)
    assert ".SKYLIGHT." not in house_ifc(house(0), CFG)


def test_model_does_not_see_skylights():
    """Условие и ответ модели одни и те же с окнами и без: словарь токенов не менялся."""
    with_lights, without = house(2), house(0)
    assert (tokens.encode(with_lights, Mode.WITH_OPENINGS, CFG)
            == tokens.encode(without, Mode.WITH_OPENINGS, CFG))
    assert vocab.fingerprint(CFG) == vocab.FROZEN
