"""Выгрузка дома в BIM (gf#392): объекты IFC4 по листу — стены, окна, двери, этажи, плиты, крыша."""

import re

import pytest
import shapely

from genfacade import cli, config, pipeline
from genfacade.datasets.synthetic import build
from genfacade.render.house3d import house_3d
from genfacade.render.ifc import IFC_FILE, counts, house_ifc
from genfacade.render.ifc_step import guid, text, value
from genfacade.schema import ElementClass, FacadeSheet, Roof, RoofKind

WINDOWS = (ElementClass.WINDOW,)
DOORS = (ElementClass.DOOR, ElementClass.GARAGE_DOOR)


def read(ifc: str) -> dict[int, tuple[str, str]]:
    """Файл STEP → {номер: (вид, атрибуты)}: читаем обратно тем, что выгрузка не использует."""
    found = {}
    for line in ifc.split("DATA;")[1].split("ENDSEC;")[0].strip().splitlines():
        m = re.fullmatch(r"#(\d+)=([A-Z0-9]+)\((.*)\);", line)
        assert m, line
        found[int(m[1])] = (m[2], m[3])
    return found


def refs(args: str) -> list[int]:
    return [int(n) for n in re.findall(r"#(\d+)", args)]


def number(sheet: FacadeSheet, classes: tuple[ElementClass, ...]) -> int:
    return sum(e.cls in classes for f in sheet.facades for e in f.elements)


@pytest.fixture(scope="module")
def sheets(cfg) -> list[FacadeSheet]:
    """Синтетические дома разных контуров и крыш: прямоугольные и Г-образные, плоские и скатные."""
    return [build.sample(k, cfg).sheet for k in range(14)]


def test_windows_and_doors_match_the_sheet(sheets, cfg):
    """Готово, когда (gf#392): число окон и дверей в IFC — как на листе; у каждого — свой вырез
    в стене и заполнение выреза; этажей и стен — столько же, сколько в листе."""
    for sheet in sheets:
        got = counts(house_ifc(sheet, cfg))
        windows, doors = number(sheet, WINDOWS), number(sheet, DOORS)
        assert windows and doors
        assert got["IFCWINDOW"] == windows and got["IFCDOOR"] == doors
        assert got["IFCOPENINGELEMENT"] == got["IFCRELVOIDSELEMENT"] == windows + doors
        assert got["IFCRELFILLSELEMENT"] == windows + doors
        assert got["IFCBUILDINGSTOREY"] == sheet.spec.floors
        assert got["IFCWALL"] >= len(sheet.facades) and got["IFCROOF"] == 1
        assert got["IFCSLAB"] >= sheet.spec.floors


def test_every_reference_resolves(sheets, cfg):
    """Ссылка `#n` указывает на сущность, записанную выше: файл не рвётся на чтении."""
    for sheet in sheets[:4]:
        entities = read(house_ifc(sheet, cfg))
        for n, (_, args) in entities.items():
            assert all(0 < r < len(entities) + 1 for r in refs(args)), n


def test_openings_sit_in_their_walls_at_sheet_sizes(house, cfg):
    """Окно в IFC — того же размера, что на листе (OverallWidth × OverallHeight), и стоит в
    вырезе стены: вырез → стена по IfcRelVoidsElement, окно → вырез по IfcRelFillsElement."""
    entities = read(house_ifc(house, cfg))
    sizes = sorted((e.w_m, e.h_m) for f in house.facades for e in f.elements
                   if e.cls in WINDOWS)
    windows = [n for n, (kind, _) in entities.items() if kind == "IFCWINDOW"]
    got = sorted((float(a[-4]), float(a[-5])) for a in (
        entities[n][1].split(",") for n in windows))
    assert [x for pair in got for x in pair] == pytest.approx([x for p in sizes for x in p])
    fills = {refs(args)[0]: refs(args)[1] for kind, args in entities.values()
             if kind == "IFCRELFILLSELEMENT"}
    voids = {refs(args)[1]: refs(args)[0] for kind, args in entities.values()
             if kind == "IFCRELVOIDSELEMENT"}
    for n in windows:
        wall = entities[voids[next(o for o, filler in fills.items() if filler == n)]]
        assert wall[0] == "IFCWALL"


@pytest.mark.parametrize("sides", [4, 8])
def test_walls_fill_the_ring_without_gaps_or_overlaps(sides, cfg):
    """Стены идут внутрь от контура и не перекрываются в углах: на выпуклом углу стена короче на
    толщину, на вогнутом длиннее — объём стен до вырезов = (контур − контур, сдвинутый внутрь) ×
    высота. Без подгонки углов объём растёт на t² × высоту в каждом выпуклом углу."""
    sheet = next(s for s in (build.sample(k, cfg).sheet for k in range(60))
                 if len(s.facades) == sides and s.spec.roof.kind is RoofKind.FLAT)
    t = cfg.ifc.wall_thickness_m
    outline = shapely.Polygon(house_3d(sheet, cfg)["corners"])
    ring = outline.area - outline.buffer(-t, join_style="mitre").area
    assert wall_volume(read(house_ifc(sheet, cfg))) == pytest.approx(
        ring * sheet.spec.eaves_m, rel=1e-3)


def wall_volume(entities: dict[int, tuple[str, str]]) -> float:
    """Объём стен без вырезов: площадь профиля каждого выдавливания × глубина."""
    total = 0.0
    for kind, args in entities.values():
        if kind != "IFCWALL":
            continue
        shape = refs(entities[refs(args)[1]][1])[0]
        for solid in refs(entities[shape][1])[1:]:
            profile, depth = refs(entities[solid][1])[0], entities[solid][1].rsplit(",", 1)[-1]
            total += shapely.Polygon(polyline(entities, profile)).area * float(depth)
    return total


def polyline(entities: dict[int, tuple[str, str]], profile: int) -> list[tuple[float, ...]]:
    line = refs(entities[profile][1])[-1]
    return [tuple(float(c) for c in re.findall(r"-?\d+\.\d+", entities[p][1]))
            for p in refs(entities[line][1])[:-1]]


def test_thickness_comes_from_the_config(house, tmp_path):
    """Толщина стены — из config/ifc.toml: своя папка настроек меняет глубину выдавливания."""
    (tmp_path / "ifc.toml").write_text("[ifc]\nwall_thickness_m = 0.55\n")
    thick = house_ifc(house, config.load(tmp_path))
    assert ",0.550000);" in thick and ",0.550000);" not in house_ifc(house, config.load())


def test_material_and_colours_come_from_the_palette(house, cfg):
    """Материал стены — IfcMaterial вида отделки главной зоны палитры."""
    kind = next(m.kind for m in house.spec.materials if m.id == "main")
    assert f"IFCMATERIAL('{kind}'" in house_ifc(house, cfg)


def test_gable_roof_is_made_of_slopes(house, cfg):
    """Скатная крыша — плиты по скатам и фронтоны в профиле стены: IfcRoof в составе несколько
    IfcSlab(ROOF), стены выше карниза, чем у плоской."""
    gabled = house.model_copy(update={"spec": house.spec.model_copy(update={
        "roof": cfg.models.spec.roof_shape.roof(RoofKind.GABLE, "roof")})})
    flat = house.model_copy(update={"spec": house.spec.model_copy(update={
        "roof": Roof(kind=RoofKind.FLAT, material="roof")})})
    assert counts(house_ifc(gabled, cfg))["IFCSLAB"] > counts(house_ifc(flat, cfg))["IFCSLAB"]
    assert house_ifc(gabled, cfg).count(".ROOF.") >= 2


def test_file_is_deterministic_and_ascii(house, cfg):
    """Тот же дом — те же GlobalId; кириллица записана `\\X2\\…` — файл читает любой просмотрщик."""
    a, b = house_ifc(house, cfg), house_ifc(house, cfg)
    ids = lambda s: re.findall(r"'([0-9A-Za-z_$]{22})'", s)  # noqa: E731
    assert ids(a) == ids(b) and len(set(ids(a))) == len(ids(a))
    assert a.isascii() and "\\X2\\" in a


def test_step_primitives():
    assert guid("a") == guid("a") != guid("b") and len(guid("a")) == 22
    assert text("a'b") == "'a''b'" and text("Дом") == "'\\X2\\0414043E043C\\X0\\'"
    assert value([1, 2.5, None, True]) == "(1,2.500000,$,.T.)"


def test_cli_writes_the_run_house(house, cfg, tmp_path):
    """`genfacade ifc <папка прогона>` кладёт house.ifc рядом с листом."""
    run = tmp_path / "run"
    run.mkdir()
    pipeline.finish(house, run, cfg, {})
    out = cli.ifc(cli._parser().parse_args(["ifc", str(run)]))
    assert out == run / IFC_FILE
    assert counts(out.read_text())["IFCWINDOW"] == number(house, WINDOWS)
