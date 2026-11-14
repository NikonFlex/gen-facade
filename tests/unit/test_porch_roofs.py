"""Навес на столбах (gf#472, `facade: Навес на столбах`, `Кровля навеса`, `Столбы навеса`,
`Навес на листе`; `data: Крыльцо под кровлей в разметке`): кодом на листе, в 3D и IFC."""

import math

import pytest
import shapely
from test_manual import FLOOR, PT, finished, ft, pt_y

from genfacade import config, porch_roofs
from genfacade.datasets import manual
from genfacade.datasets.manual import BadMarkup, Markup
from genfacade.porch_roofs import Part
from genfacade.render.house3d import house_3d
from genfacade.render.ifc import house_ifc
from genfacade.render.svg import deck_fill, pen_for, sheet_svg, tops
from genfacade.schema import (
    Element,
    ElementClass,
    FacadeSheet,
    HouseSpec,
    PorchKind,
    PorchRoof,
    RoofKind,
)

CFG = config.load()
SHEET = manual.house(finished(), CFG.data.manual)[0].sheet
LENGTHS = [f.side.length_m for f in SHEET.facades]
LONG = LENGTHS.index(max(LENGTHS))  # стена, на которой x 0–5 м ложатся целиком
POST = CFG.sheet.porch_roof.post_m
EAVES = SHEET.spec.eaves_m
HOUSE_TAN = math.tan(math.radians(SHEET.spec.roof.pitch_deg))  # уклон кровли дома


def awning(kind: PorchKind = PorchKind.SHED, x=(1.0, 5.0), depth=2.4, low=2.0, high=2.6, posts=3,
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
    """Сценарии «Навес с уклоном по разметке» и «Односкатный навес»: уклон 9,5° (дом 32°):
    профиль 2,4–2,6 у стены и 2,0–2,2 у края; три столба 0,15 м на 0,375, 2,0 и 3,625 м вдоль
    отрезка, в 2,025 м от стены, высотой по низу кровли над ними (2,0625 м)."""
    a = built()
    assert flat(a.profile) == pytest.approx(flat([(0.0, 2.4), (2.4, 2.0), (2.4, 2.2), (0.0, 2.6)]))
    assert a.length == pytest.approx(4.0) and POST == pytest.approx(0.15)
    spots = [along(a, q.at) for q in a.posts]
    assert [s[0] for s in spots] == pytest.approx([0.375, 2.0, 3.625])
    assert [s[1] for s in spots] == pytest.approx([2.025] * 3)
    assert [q.top for q in a.posts] == pytest.approx([2.0 + 0.6 / 2.4 * 0.375 / 1.5] * 3)


def test_gable_roof_pitch_of_house():
    """Сценарий «Двускатный навес»: уклон по разметке 31,4° на 0,6° от дома (32°) — как у дома:
    низ 1,6 м по краям и 1,6 + 1,8 · tg 32° на коньке; выше конька ниже карниза — кровля кончается
    на стене; столбы на 0,375 и 3,225 м, высота по низу ската над ними."""
    a = built(kind=PorchKind.GABLE, depth=1.4, low=1.6, high=2.9, x=(0.0, 3.6), posts=2)
    ridge = 1.6 + 1.8 * HOUSE_TAN
    assert a.outward and a.sweep[1] == pytest.approx(1.4) and a.reach == 0.0
    assert flat(a.profile) == pytest.approx(flat([(0.0, 1.6), (1.8, ridge), (3.6, 1.6),
                                                  (3.6, 1.8), (1.8, ridge + 0.2), (0.0, 1.8)]))
    assert [along(a, q.at)[0] for q in a.posts] == pytest.approx([0.375, 3.225])
    assert [q.top for q in a.posts] == pytest.approx([1.6 + HOUSE_TAN * 0.375] * 2)


def test_gable_roof_steeper_than_house_reaches_house_roof():
    """Сценарий «Навес круче дома»: уклон по разметке 45° — конёк 3,4 м выше карниза 2,74 м, кровля
    продлена за стену внутрь дома до ската кровли: на (3,4 − 2,74) / tg 32°."""
    a = built(kind=PorchKind.GABLE, depth=1.4, low=1.6, high=3.6, x=(0.0, 3.6), posts=2)
    assert a.profile[1] == pytest.approx((1.8, 3.4))
    assert a.reach == pytest.approx(-(3.4 - EAVES) / HOUSE_TAN)
    assert a.sweep[1] == pytest.approx(1.4 - a.reach)


def test_gable_planes_continue_house_roof():
    """Кровля навеса — плоские грани (рисунок кровли дома идёт по ним без шва), нижняя грань у
    стены доходит до скрытой части: у двускатного две грани, у плоского грани нет."""
    assert len(built(kind=PorchKind.GABLE).planes) == 2
    assert built(kind=PorchKind.FLAT).planes == []


def test_gable_sheet_views():
    """Сценарий «Двускатный навес на листе»: на виде своей стены — треугольник фронтона шириной
    3,6 м от 1,6 м до конька; сбоку — скат шириной 1,4 м от стены до края."""
    sheet = awning(kind=PorchKind.GABLE, depth=1.4, low=1.6, high=2.9, x=(0.0, 3.6), posts=2)
    (front,) = parts_of(sheet, LONG, Part.ROOF)
    xs, zs = [p[0] for p in front], [p[1] for p in front]
    top = 1.6 + 1.8 * HOUSE_TAN + 0.2
    assert (max(xs) - min(xs), min(zs), max(zs)) == pytest.approx((3.6, 1.6, top))
    assert any(p[1] == pytest.approx(top) and p[0] == pytest.approx(min(xs) + 1.8) for p in front)
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
    x 1–5 м и три столба шириной 0,15 м от земли до 2,06 м."""
    sheet = awning()
    (band,) = parts_of(sheet, LONG, Part.ROOF)
    xs, zs = [p[0] for p in band], [p[1] for p in band]
    assert (max(xs) - min(xs), min(zs), max(zs)) == pytest.approx((4.0, 2.0, 2.6))
    assert min(xs) == pytest.approx(1.0) or max(xs) == pytest.approx(1.0 + 4.0)
    posts = parts_of(sheet, LONG, Part.POST)
    assert len(posts) == 3
    assert all(max(p[0] for p in q) - min(p[0] for p in q) == pytest.approx(0.15) for q in posts)
    assert all(max(p[1] for p in q) == pytest.approx(2.0 + 0.25 * 0.375 / 1.5 * 1.0) for q in posts)


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
    """3D: кровля-плита — плоскими гранями `awning_faces` (как скаты дома), столбы с цветом из
    настроек; плоская кровля — призмой по профилю; без навеса — ничего."""
    items = house_3d(awning(), CFG)["items"]
    assert len(items["awning_faces"]) == 1 and items["awnings"] == [] and len(items["posts"]) == 3
    assert items["posts"][0]["color"] == CFG.sheet.porch_roof.post_fill
    flat_roof = house_3d(awning(PorchKind.FLAT), CFG)["items"]
    assert len(flat_roof["awnings"]) == 1 and flat_roof["awning_faces"] == []
    empty = house_3d(SHEET, CFG)["items"]
    assert empty["awnings"] == [] and empty["awning_faces"] == []


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
    конька — как у дома; кровля шире щипца на свес дома с каждой стороны; столбы под скатом на
    свесе 0,3 м от края."""
    a = continued(GABLE_WALL)
    ridge = EAVES + TAN * LENGTHS[GABLE_WALL] / 2
    assert a.outward and a.sweep[1] == pytest.approx(1.5 - OVER) and a.reach == pytest.approx(OVER)
    assert a.length == pytest.approx(LENGTHS[GABLE_WALL] + 2 * OVER)
    end = EAVES - TAN * OVER
    assert [z for _, z in a.profile[:3]] == pytest.approx([end, ridge, end])
    assert a.profile[1][0] == pytest.approx(a.length / 2)
    inset = CFG.sheet.porch_roof.overhang_m + POST / 2
    assert [q.top for q in a.posts][0] == pytest.approx(EAVES + TAN * inset)
    assert a.kind is RoofKind.GABLE


def test_continued_at_eave_wall():
    """Сценарий «Продолжение у карнизной стены»: скат продолжается вниз от свеса дома (0,5 м)
    до выноса 1,5 м с тем же уклоном: низ кровли на краю ниже карниза на 1,5·tg 30°; столбы на
    свесе 0,3 м от края — под ним."""
    a = continued(EAVE_WALL, x=(1.0, 5.0))
    assert not a.outward and a.sweep[1] == pytest.approx(4.0)
    assert a.profile[0] == pytest.approx((OVER, EAVES - TAN * OVER))
    assert a.profile[1] == pytest.approx((1.5, EAVES - TAN * 1.5))
    thick = CFG.sheet.roof.thickness_m
    assert a.profile[2][1] - a.profile[1][1] == pytest.approx(thick)
    out = 1.5 - CFG.sheet.porch_roof.overhang_m - POST / 2
    assert {round(q.top, 6) for q in a.posts} == {round(EAVES - TAN * out, 6)}


def test_continued_inside_house_overhang():
    """Вынос не больше свеса дома — дом уже накрывает навес: второй кровли нет, столбы есть."""
    a = continued(EAVE_WALL, x=(1.0, 5.0), depth=0.4)
    assert a.profile == [] and len(a.posts) == 3


def test_manual_main_kind():
    """Сценарий «Навес — продолжение крыши»: вид `main` доходит до параметров дома."""
    sample, _ = manual.house(markup_with(kind="main"), CFG.data.manual)
    assert sample.sheet.spec.porch_roofs[0].kind is PorchKind.MAIN


def pillars_markup(*centres_ft: float) -> Markup:
    """Дом разметки с навесом на стороне входа и `pillar` на том же виде: центры — футы от края."""
    raw = markup_with().model_dump(mode="json")
    raw["sides"][0]["elements"] += [
        {"cls": "pillar", "box": [100.0 + c * PT - 1.0, pt_y(8), 100.0 + c * PT + 1.0, pt_y(0)]}
        for c in centres_ft]
    return Markup.model_validate(raw)


def test_manual_posts_from_pillars():
    """Сценарий «Столбы по разметке»: центры `pillar` на виде стены навеса — положения столбов;
    одного `pillar` при трёх столбах отметки мало — столбы равномерно."""
    given = manual.house(pillars_markup(3, 7), CFG.data.manual)[0].sheet.spec.porch_roofs[0]
    assert given.post_x_m == pytest.approx([ft(3), ft(7)])
    awnings = porch_roofs.find(manual.house(pillars_markup(3, 7), CFG.data.manual)[0].sheet,
                               CFG.sheet)
    assert [round(along(awnings[0], q.at)[0] + given.x_m[0], 3) for q in awnings[0].posts] == [
        round(ft(3), 3), round(ft(7), 3)]
    few = manual.house(pillars_markup(3), CFG.data.manual)[0].sheet.spec.porch_roofs[0]
    assert few.post_x_m == []


def wall_pillars(markup: Markup) -> int:
    """Сколько `pillar` осталось плашками на стенах листа."""
    sheet = manual.house(markup, CFG.data.manual)[0].sheet
    return sum(e.cls is ElementClass.PILLAR for f in sheet.facades for e in f.elements)


def test_pillars_of_awning_not_on_wall():
    """Сценарий «Столбы навеса не рисуются на стене»: два `pillar`, ставшие столбами навеса, на
    стене не остаются; одного при трёх столбах отметки мало — он остаётся плашкой."""
    assert wall_pillars(pillars_markup(3, 7)) == 0
    assert wall_pillars(pillars_markup(3)) == 1


def terrace(x=(2.0, 8.0), porch=False, **mark) -> FacadeSheet:
    """Дом разметки с навесом на стороне входа (дверь на 5–7 футах); `porch` — крыльцо у двери."""
    sheet = manual.house(markup_with(x=[100.0 + x[0] * PT, 100.0 + x[1] * PT], **mark),
                         CFG.data.manual)[0].sheet
    if not porch:
        return sheet
    step = Element(id="p1", cls=ElementClass.PORCH, x_m=ft(4), y_m=0.0, w_m=ft(4),
                   h_m=sheet.spec.plinth_m, floor=1)
    front = sheet.facades[0]
    facades = [front.model_copy(update={"elements": [*front.elements, step]}), *sheet.facades[1:]]
    return sheet.model_copy(update={"facades": facades})


def test_deck_under_awning():
    """Сценарий «Настил под навесом»: пол на 0,3048 м, навес 2–8 футов, вынос 2,4 м, дверь на
    5–7 футах — плита 1,829 × 2,4 м от земли до 0,3048 м, цветом цоколя; на виде стены — полоса
    ширины отрезка, на боковом — глубины выноса; в 3D `decks`, в IFC плита."""
    sheet = terrace()
    (a,) = porch_roofs.find(sheet, CFG.sheet)
    (deck,) = a.decks
    top = sheet.spec.plinth_m
    assert (deck.z0, deck.z1) == pytest.approx((0.0, top))
    assert shapely.Polygon(deck.ring).area == pytest.approx(ft(6) * 2.4)
    widths = sorted(round(max(p[0] for p in s) - min(p[0] for p in s), 3)
                    for k in range(len(LENGTHS)) for s in parts_of(sheet, k, Part.DECK))
    assert widths == [round(ft(6), 3), 2.4, 2.4]  # лицо и два боковых вида
    items = house_3d(sheet, CFG)["items"]
    assert [d["color"] for d in items["decks"]] == [deck_fill(pen_for(sheet, CFG))]
    assert house_ifc(sheet, CFG).count("IFCSLAB(") == house_ifc(SHEET, CFG).count("IFCSLAB(") + 1
    assert 'class="porch-deck"' in sheet_svg(sheet, CFG)


def test_no_deck_without_door_or_floor():
    """Сценарий «Настил под навесом»: у отрезка без двери (карпорт на земле) и при поле у земли
    настила нет."""
    assert porch_roofs.find(terrace(x=(8.5, 11.0)), CFG.sheet)[0].decks == []
    low = terrace()
    low = low.model_copy(update={"spec": low.spec.model_copy(update={"plinth_m": 0.1})})
    assert porch_roofs.find(low, CFG.sheet)[0].decks == []
    assert house_3d(low, CFG)["items"]["decks"] == []


def test_deck_continues_porch_without_double_slab():
    """Сценарий «Настил продолжает крыльцо»: крыльцо двери на 4–8 футах — настил на 2–4 футах
    (левее него), справа от крыльца ничего: плит над крыльцом нет."""
    (a,) = porch_roofs.find(terrace(porch=True), CFG.sheet)
    (deck,) = a.decks
    assert shapely.Polygon(deck.ring).area == pytest.approx(ft(2) * 2.4)


def test_deck_threshold_is_the_porch_threshold():
    """Допуск настила — тот же, что у крыльца двери (`checks.porch_min_m`): одно значение."""
    assert CFG.sheet.porch_roof.deck_min_m == CFG.checks.porch_min_m


GABLE_FRONT = {"kind": PorchKind.GABLE, "depth": 1.4, "low": 1.6, "high": 2.9, "x": (0.0, 3.6),
               "posts": 2}


def test_gable_front_is_filled():
    """Сценарий «Фронтон двускатного навеса закрыт»: наружный торец — треугольник под скатами
    (3,6 м у основания, от 1,6 м до конька 1,6 + 1,8 · tg 32°), в плоскости торца, в 1,4 м от стены;
    у односкатного фронтона нет."""
    a = built(**GABLE_FRONT)
    ridge = 1.6 + 1.8 * HOUSE_TAN
    assert sorted(z for *_, z in a.gable) == pytest.approx(sorted([1.6, 1.6, ridge]))
    assert {round(along(a, p[:2])[1], 6) for p in a.gable} == {1.4}
    assert shapely.Polygon([(along(a, p[:2])[0], p[2]) for p in a.gable]).area == pytest.approx(
        3.6 * (ridge - 1.6) / 2)
    assert built().gable == [] and built(kind=PorchKind.FLAT).gable == []


def test_gable_fill_on_sheet_3d_and_ifc():
    """Фронтон навеса: на листе — заливка перед лентой кровли, в 3D — `awning_gables` стены дома,
    в IFC — стена IfcWall сверх стен дома; односкатному навесу ничего."""
    sheet = awning(**GABLE_FRONT)
    (fill,) = parts_of(sheet, LONG, Part.GABLE)
    assert max(p[1] for p in fill) == pytest.approx(1.6 + 1.8 * HOUSE_TAN)
    assert 'class="porch-gable"' in sheet_svg(sheet, CFG)
    assert len(house_3d(sheet, CFG)["items"]["awning_gables"]) == 1
    assert house_3d(awning(), CFG)["items"]["awning_gables"] == []
    assert house_ifc(sheet, CFG).count("IFCWALL(") == house_ifc(SHEET, CFG).count("IFCWALL(") + 1
