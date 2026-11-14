"""Навес на столбах (gf#472, `facade: Навес на столбах`, `Кровля навеса`, `Столбы навеса`,
`Навес на листе`; `data: Крыльцо под кровлей в разметке`): кодом на листе, в 3D и IFC."""

import math

import pytest
from test_manual import FLOOR, PT, finished, ft, pt_y

from genfacade import config, porch_roofs
from genfacade.datasets import manual
from genfacade.datasets.manual import BadMarkup, Markup
from genfacade.porch_roofs import Part
from genfacade.render.house3d import house_3d
from genfacade.render.ifc import house_ifc
from genfacade.render.svg import sheet_svg, tops
from genfacade.schema import FacadeSheet, HouseSpec, PorchKind, PorchRoof, RoofKind

CFG = config.load()
SHEET = manual.house(finished(), CFG.data.manual)[0].sheet
LENGTHS = [f.side.length_m for f in SHEET.facades]
LONG = LENGTHS.index(max(LENGTHS))  # стена, на которой x 0–5 м ложатся целиком
POST = CFG.sheet.porch_roof.post_m


def awning(kind: PorchKind = PorchKind.SHED, x=(1.0, 5.0), depth=2.4, low=2.4, high=3.0, posts=3,
           side: int = LONG) -> FacadeSheet:
    """Дом разметки с одним навесом."""
    given = PorchRoof(side=side, x_m=x, depth_m=depth, bottom_m=low, top_m=high, kind=kind,
                      posts=posts)
    spec = SHEET.spec.model_copy(update={"porch_roofs": [given]})
    return SHEET.model_copy(update={"spec": spec})


def built(**kw) -> porch_roofs.Awning:
    return porch_roofs.find(awning(**kw), CFG.sheet)[0]


def flat(points) -> list[float]:
    return [v for p in points for v in p]


def along(a: porch_roofs.Awning, p) -> tuple[float, float]:
    """Точка плана → (вдоль стены от левого края навеса, наружу от стены)."""
    d = (p[0] - a.left[0], p[1] - a.left[1])
    return d[0] * a.u[0] + d[1] * a.u[1], d[0] * a.n[0] + d[1] * a.n[1]


def test_shed_roof_and_posts():
    """Сценарий «Односкатный навес»: профиль 2,8–3,0 у стены и 2,4–2,6 у края; три столба 0,15 м
    высотой 2,4 м на 1,075, 3,0 и 4,925 м и в 2,325 м от стены."""
    a = built()
    assert flat(a.profile) == pytest.approx(flat([(0.0, 2.8), (2.4, 2.4), (2.4, 2.6), (0.0, 3.0)]))
    assert a.length == pytest.approx(4.0) and POST == pytest.approx(0.15)
    spots = [along(a, q.at) for q in a.posts]
    assert [s[0] for s in spots] == pytest.approx([0.075, 2.0, 3.925])
    assert [s[1] for s in spots] == pytest.approx([2.325] * 3)
    assert [q.top for q in a.posts] == pytest.approx([2.4] * 3)


def test_gable_roof():
    """Сценарий «Двускатный навес»: конёк поперёк стены посередине отрезка (st-102483): в сечении
    вдоль стены низ 2,55 м по краям и 3,35 м на коньке в 1,8 м от края, верх выше на 0,2 м;
    выдавлено на вынос 1,4 м; столбы на 0,075 и 3,525 м, высотой по низу ската над ними."""
    a = built(kind=PorchKind.GABLE, depth=1.4, low=2.55, high=3.55, x=(0.0, 3.6), posts=2)
    assert a.outward and a.sweep[1] == pytest.approx(1.4)
    assert flat(a.profile) == pytest.approx(flat([(0.0, 2.55), (1.8, 3.35), (3.6, 2.55),
                                                  (3.6, 2.75), (1.8, 3.55), (0.0, 2.75)]))
    assert [along(a, q.at)[0] for q in a.posts] == pytest.approx([0.075, 3.525])
    assert [q.top for q in a.posts] == pytest.approx([2.55 + 0.8 * 0.075 / 1.8] * 2)


def test_gable_sheet_views():
    """Сценарий «Двускатный навес на листе»: на виде своей стены — треугольник фронтона шириной
    3,6 м от 2,55 до 3,55 м; сбоку — скат шириной 1,4 м от стены до края."""
    sheet = awning(kind=PorchKind.GABLE, depth=1.4, low=2.55, high=3.55, x=(0.0, 3.6), posts=2)
    (front,) = parts_of(sheet, LONG, Part.ROOF)
    xs, zs = [p[0] for p in front], [p[1] for p in front]
    assert (max(xs) - min(xs), min(zs), max(zs)) == pytest.approx((3.6, 2.55, 3.55))
    assert any(p[1] == pytest.approx(3.55) and p[0] == pytest.approx(min(xs) + 1.8) for p in front)
    side = [s for k in range(len(LENGTHS)) if k != LONG for s in parts_of(sheet, k, Part.ROOF)]
    assert side and all(max(p[0] for p in s) - min(p[0] for p in s) == pytest.approx(1.4)
                        for s in side)


def test_flat_roof():
    """Сценарий «Плоский навес»: прямоугольник 2 × 0,2 м от 2,5 до 2,7 м; не тоньше кровли дома."""
    a = built(kind=PorchKind.FLAT, depth=2.0, low=2.5, high=2.7)
    assert flat(a.profile) == pytest.approx(flat([(0.0, 2.5), (2.0, 2.5), (2.0, 2.7), (0.0, 2.7)]))
    thin = built(kind=PorchKind.FLAT, depth=2.0, low=2.5, high=2.55)
    assert max(z for _, z in thin.profile) == pytest.approx(2.5 + CFG.sheet.roof.thickness_m)


def test_hip_is_gable():
    """Сценарий «Вальмовый навес»: такой же, как двускатный."""
    assert built(kind=PorchKind.HIP).profile == built(kind=PorchKind.GABLE).profile
    assert built(kind=PorchKind.HIP).kind is RoofKind.GABLE


def test_posts_count():
    """Один столб — посередине, нуль — без столбов."""
    assert along(built(posts=1), built(posts=1).posts[0].at)[0] == pytest.approx(2.0)
    assert built(posts=0).posts == []


def test_old_spec_reads_without_porch_roofs():
    """Сценарий «Старый файл без навесов»: файл без поля — навесов нет."""
    raw = SHEET.spec.model_dump(mode="json")
    raw.pop("porch_roofs")
    assert HouseSpec.model_validate(raw).porch_roofs == []
    assert porch_roofs.find(SHEET, CFG.sheet) == []


def parts_of(sheet: FacadeSheet, k: int, part: Part) -> list:
    return [shape for p, shape in tops(sheet, CFG)[k].awnings if p is part]


def test_sheet_front_view():
    """Сценарий «Навес на листе»: на виде своей стены полоса кровли 4 × 0,6 м от 2,4 до 3,0 м на
    x 1–5 м и три столба шириной 0,15 м от земли до 2,4 м."""
    sheet = awning()
    (band,) = parts_of(sheet, LONG, Part.ROOF)
    xs, zs = [p[0] for p in band], [p[1] for p in band]
    assert (max(xs) - min(xs), min(zs), max(zs)) == pytest.approx((4.0, 2.4, 3.0))
    assert min(xs) == pytest.approx(1.0) or max(xs) == pytest.approx(1.0 + 4.0)
    posts = parts_of(sheet, LONG, Part.POST)
    assert len(posts) == 3
    assert all(max(p[0] for p in q) - min(p[0] for p in q) == pytest.approx(0.15) for q in posts)
    assert all(max(p[1] for p in q) == pytest.approx(2.4) for q in posts)


def test_sheet_side_and_back_views():
    """Сценарий «Навес на листе»: на виде противоположной стены навеса нет; на боковых —
    профиль шириной 2,4 м, хотя бы на одном."""
    sheet = awning()
    count = len(LENGTHS)
    opposite = (LONG + count // 2) % count
    assert parts_of(sheet, opposite, Part.ROOF) == []
    sides = [k for k in range(count) if k not in (LONG, opposite)]
    profiles = [parts_of(sheet, k, Part.ROOF) for k in sides]
    assert any(profiles)
    for shape in (s for ps in profiles for s in ps):
        assert max(p[0] for p in shape) - min(p[0] for p in shape) == pytest.approx(2.4)


def test_sheet_svg_draws_awning():
    """Лист рисует кровлю и столбы навеса: без навеса их нет."""
    svg = sheet_svg(awning(), CFG)
    assert svg.count('class="porch-roof"') >= 1 and svg.count('class="porch-post"') >= 3
    assert "porch-" not in sheet_svg(SHEET, CFG)


def test_house3d_has_awning():
    """3D: призма кровли по профилю и столбы с цветом из настроек."""
    items = house_3d(awning(), CFG)["items"]
    assert len(items["awnings"]) == 1 and len(items["posts"]) == 3
    assert items["posts"][0]["color"] == CFG.sheet.porch_roof.post_fill
    assert house_3d(SHEET, CFG)["items"]["awnings"] == []


def test_ifc_has_awning():
    """IFC: IfcRoof навеса сверх крыши дома и по IfcColumn на столб."""
    base, text = house_ifc(SHEET, CFG), house_ifc(awning(), CFG)
    assert text.count("IFCROOF(") == base.count("IFCROOF(") + 1
    assert text.count("IFCCOLUMN(") == base.count("IFCCOLUMN(") + 3


def markup_with(**mark) -> Markup:
    """Дом разметки 12' × 20' с навесом на стороне входа: x и y в pt листа."""
    raw = finished().model_dump(mode="json")
    given = {"side": 0, "x": [100.0 + 2 * PT, 100.0 + 8 * PT], "y": [pt_y(9), pt_y(7)],
             "kind": "shed", "posts": 3, "depth_m": 2.4} | mark
    raw["porch_roofs"] = [given]
    return Markup.model_validate(raw)


def test_manual_passes_awning_to_house():
    """Сценарий «Терраса под односкатной кровлей»: навес в параметрах дома — края в метрах вдоль
    стены, низ и верх над землёй, вынос и число столбов."""
    sample, _ = manual.house(markup_with(), CFG.data.manual)
    (given,) = sample.sheet.spec.porch_roofs
    assert given.x_m == pytest.approx((ft(2), ft(8)))
    plinth = sample.sheet.spec.plinth_m
    assert (given.bottom_m, given.top_m) == pytest.approx((plinth + ft(7), plinth + ft(9)))
    assert (given.depth_m, given.posts, given.kind) == (2.4, 3, RoofKind.SHED)


def test_manual_keeps_awning_beyond_wall():
    """Сценарий «Навес за краем стены»: терраса за углом не обрезается и не отказ."""
    edge = 100.0 + 12 * PT
    sample, _ = manual.house(markup_with(x=[edge + 10.0, edge + 100.0]), CFG.data.manual)
    assert sample.sheet.spec.porch_roofs[0].x_m[0] > sample.sheet.facades[0].side.length_m


@pytest.mark.parametrize("y", [[pt_y(7), pt_y(9)], [FLOOR + 200.0, FLOOR + 100.0]])
def test_manual_refuses_bad_marks(y):
    """Сценарий «Навес с кровлей под землёй»: верх не выше низа или низ не над землёй — отказ
    с текстом."""
    with pytest.raises(BadMarkup, match="навес"):
        manual.house(markup_with(y=y), CFG.data.manual)


def test_sheet_profile_only_on_nearer_side():
    """Навес у края стены виден профилем только с ближней боковой стены: с дальней он за домом."""
    sheet = awning(x=(0.0, 1.0))
    count = len(LENGTHS)
    sides = [(LONG + 1) % count, (LONG - 1) % count]
    assert sorted(len(parts_of(sheet, k, Part.ROOF)) for k in sides) == [0, 1]


# ——— продолжение крыши дома (`facade: Кровля навеса`, вид `main`) ———

PITCH = 30.0
TAN = math.tan(math.radians(PITCH))
EAVES = SHEET.spec.eaves_m
OVER = SHEET.spec.roof.overhang_m
EAVE_WALL = 1
GABLE_WALL = 0


def continued(side: int, x=(0.0, LENGTHS[GABLE_WALL]), depth=1.5) -> porch_roofs.Awning:
    """Навес-продолжение на доме с уклоном 30°; низ и верх с разметки (2,0 и 3,0 м) ни на что не
    влияют."""
    sheet = awning(PorchKind.MAIN, x=x, depth=depth, low=2.0, high=3.0, side=side)
    roof_30 = sheet.spec.roof.model_copy(update={"pitch_deg": PITCH})
    sheet = sheet.model_copy(update={"spec": sheet.spec.model_copy(update={"roof": roof_30})})
    return porch_roofs.find(sheet, CFG.sheet)[0]


def test_continued_at_gable_wall():
    """Сценарий «Продолжение у щипцовой стены»: конёк и скаты идут дальше — сечение щипца
    выдавлено от свеса дома (0,5 м) до выноса 1,5 м, то есть кровля длиннее на 1,0 м; высота
    конька — как у дома; столбы стоят под скатом: у края стены — на высоте карниза."""
    a = continued(GABLE_WALL)
    ridge = EAVES + TAN * LENGTHS[GABLE_WALL] / 2
    assert a.outward and a.sweep[1] == pytest.approx(1.5 - OVER) and a.reach == pytest.approx(OVER)
    bottom = [z for _, z in a.profile[:3]]
    assert bottom == pytest.approx([EAVES, ridge, EAVES])
    assert a.profile[1][0] == pytest.approx(LENGTHS[GABLE_WALL] / 2)
    assert [q.top for q in a.posts][0] == pytest.approx(EAVES + TAN * 0.075)
    assert a.kind is RoofKind.GABLE


def test_continued_at_eave_wall():
    """Сценарий «Продолжение у карнизной стены»: скат продолжается вниз от свеса дома (0,5 м)
    до выноса 1,5 м с тем же уклоном: низ кровли на краю ниже карниза на 1,5·tg 30°; столбы на
    наружном крае — под ним."""
    a = continued(EAVE_WALL, x=(1.0, 5.0))
    assert not a.outward and a.sweep[1] == pytest.approx(4.0)
    assert a.profile[0] == pytest.approx((OVER, EAVES - TAN * OVER))
    assert a.profile[1] == pytest.approx((1.5, EAVES - TAN * 1.5))
    thick = CFG.sheet.roof.thickness_m
    assert a.profile[2][1] - a.profile[1][1] == pytest.approx(thick)
    assert {round(q.top, 6) for q in a.posts} == {round(EAVES - TAN * (1.5 - POST / 2), 6)}


def test_continued_inside_house_overhang():
    """Вынос не больше свеса дома — дом уже накрывает навес: второй кровли нет, столбы есть."""
    a = continued(EAVE_WALL, x=(1.0, 5.0), depth=0.4)
    assert a.profile == [] and len(a.posts) == 3


def test_manual_main_kind():
    """Сценарий «Навес — продолжение крыши»: вид `main` доходит до параметров дома."""
    sample, _ = manual.house(markup_with(kind="main"), CFG.data.manual)
    assert sample.sheet.spec.porch_roofs[0].kind is PorchKind.MAIN
