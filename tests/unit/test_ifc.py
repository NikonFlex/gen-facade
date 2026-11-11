"""Выгрузка дома в BIM (gf#392): объекты IFC4 по листу — стены, окна, двери, этажи, плиты, крыша."""

import math
import re

import pytest
import shapely

from genfacade import cli, config, pipeline, roof
from genfacade.datasets.synthetic import build
from genfacade.render.house3d import house_3d
from genfacade.render.ifc import IFC_FILE, IfcHouse, counts, house_ifc
from genfacade.render.ifc_step import guid, text, value
from genfacade.render.svg import sheet_svg
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
    bare = re.sub(r"'[^']*'", "''", args)  # без строк: '#33373b' — имя стиля-цвета, не ссылка
    return [int(n) for n in re.findall(r"#(\d+)", bare)]


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


def of_class(ifc: str, cls: ElementClass) -> int:
    """Сколько объектов IFC несут в наборе GenFacade класс элемента листа."""
    return ifc.count(f"IFCPROPERTYSINGLEVALUE('Class',$,IFCLABEL('{cls}'),$)")


def test_shutters_canopies_and_porches_match_the_sheet(sheets, cfg):
    """Ставни (IfcShadingDevice SHUTTER), козырьки (IfcSlab ROOF) и крыльца (IfcSlab BASESLAB) —
    столько же, сколько элементов этих классов на листе; есть дома, где есть каждый из видов."""
    seen = set()
    for sheet in sheets:
        text = house_ifc(sheet, cfg)
        blinds = number(sheet, (ElementClass.BLIND,))
        canopies = number(sheet, (ElementClass.CANOPY,))
        porches = number(sheet, (ElementClass.PORCH,))
        assert counts(text).get("IFCSHADINGDEVICE", 0) == blinds
        assert of_class(text, ElementClass.BLIND) == blinds
        assert text.count(".SHUTTER.") == blinds
        assert of_class(text, ElementClass.CANOPY) == canopies
        assert of_class(text, ElementClass.PORCH) == porches
        assert text.count(".BASESLAB.") == porches
        seen |= {n for n, v in (("blind", blinds), ("canopy", canopies), ("porch", porches)) if v}
    assert seen == {"blind", "canopy", "porch"}


def test_shutters_stand_on_the_wall_at_config_thickness(sheets, cfg):
    """Ставня выступает из стены на `ifc.shutter_m` и лежит на этаже своего окна."""
    sheet = next(s for s in sheets if number(s, (ElementClass.BLIND,)))
    text = house_ifc(sheet, cfg)
    entities = read(text)
    solids = [a for k, a in entities.values() if k == "IFCEXTRUDEDAREASOLID"]
    assert any(a.endswith(f",{cfg.ifc.shutter_m:.6f}") for a in solids)
    assert "IFCRELCONTAINEDINSPATIALSTRUCTURE" in text


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


@pytest.mark.slow
@pytest.mark.parametrize("kind", [RoofKind.GABLE, RoofKind.HIP, RoofKind.SHED])
def test_walls_do_not_stick_out_above_the_roof(kind, sheets, cfg):
    """Готово, когда (gf#392, 10.11): ни одна точка стены — ни на наружной, ни на внутренней
    грани — не выше ската над ней и не вровень с ним (вровень мерцает в просмотрщике). Стена
    толщиной t выдавлена внутрь, а скат односкатной крыши над внутренней гранью ниже, чем над
    наружной: верх по наружной грани торчал над кровлей. На вогнутом углу Г-дома одной высоты
    (gf#431) стена продолжена за угол, а кровля над углом ниже её торца."""
    assert _checked_below_roof([_with_roof(s, kind, cfg) for s in sheets], cfg)


def _with_roof(sheet: FacadeSheet, kind: RoofKind, cfg) -> FacadeSheet:
    """Лист с крышей дома вида kind и без крыш частей: они у синтетики другого вида."""
    return sheet.model_copy(update={"spec": sheet.spec.model_copy(update={
        "roof": cfg.models.spec.roof_shape.roof(kind, "roof")}), "roofs": [], "wall_gables": []})


def _checked_below_roof(sheets: list[FacadeSheet], cfg) -> int:
    """Сколько точек стен проверено: каждая не выше ската над ней и не вровень с ним."""
    t, checked = cfg.ifc.wall_thickness_m, 0
    for sheet in sheets:
        house = roof.roofs(sheet)
        if house is None:
            continue
        builder = IfcHouse(sheet, cfg, IFC_FILE)
        for k, f in enumerate(sheet.facades):
            wall = builder.data["walls"][k]
            (lx, ly), (rx, ry) = wall["left"], wall["right"]
            length = ((rx - lx) ** 2 + (ry - ly) ** 2) ** 0.5
            u = ((rx - lx) / length, (ry - ly) / length)
            for ring in builder._trim(k, builder._wall_shape(k, f)):
                for x, z in ring:
                    for depth in (0.0, t):  # от наружной грани внутрь: вдоль −(u[1], −u[0])
                        px, py = lx + u[0] * x - u[1] * depth, ly + u[1] * x + u[0] * depth
                        top = builder.roof_top((px, py))
                        if top is not None:
                            checked += 1
                            assert z <= top - cfg.ifc.roof_seat_m + 1e-6, (k, x, z, depth, top)
    return checked


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


def _roof_plates(text: str) -> list[tuple[list[float], list[float]]]:
    """Плиты кровли файла, прочитанные обратно: (z верхней грани, z нижней) по вершинам профиля,
    перенесённым в мир по размещению плиты и направлению выдавливания."""
    ents = read(text)
    nums = lambda n: [float(v) for v in re.findall(r"-?\d+\.\d+", ents[n][1])]  # noqa: E731
    plates = []
    for _, (kind, args) in ents.items():
        if kind != "IFCSLAB" or ".ROOF." not in args:
            continue
        shape_ref, place_ref = refs(args)[1], refs(args)[0]
        rep = refs(ents[refs(ents[shape_ref][1])[0]][1])[1:]
        solid = ents[rep[0]][1] if ents[rep[0]][0] == "IFCEXTRUDEDAREASOLID" else None
        assert solid, ents[rep[0]]
        profile, _, direction = refs(solid)
        depth = float(solid.rsplit(",", 1)[1])
        origin, zref, xref = refs(ents[refs(ents[place_ref][1])[1]][1])
        o, z, x = nums(origin), nums(zref), nums(xref)
        y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
        pts = refs(ents[refs(ents[profile][1])[0]][1])
        d = nums(direction)
        dz = d[0] * x[2] + d[1] * y[2] + d[2] * z[2]  # вертикальная составляющая направления
        tops = [o[2] + nums(p)[0] * x[2] + nums(p)[1] * y[2] for p in pts]
        plates.append((tops, [t + depth * dz for t in tops]))
    return plates


def _gabled_35(house):
    """Простой дом с двускатной крышей 35°, свесом 0,4 м (толщина кровли — из настроек)."""
    sheet = house.model_copy(update={"spec": house.spec.model_copy(update={"roof": Roof(
        kind=RoofKind.GABLE, material="roof", pitch_deg=35, overhang_m=0.4)}), "roofs": [],
        "wall_gables": []})
    return sheet


def test_roof_plate_stands_on_the_slope_by_config_thickness(house, cfg):
    """Требование «Толщина кровли» (gf#447): низ плиты ската — грань ската, верх выше неё на
    толщину по вертикали, торец вертикальный. Двускатная 35°, карниз 3,25, свес 0,4, толщина 0,2:
    низ у края свеса 3,25 − 0,4·tg35° ≈ 2,97, верх торца ≈ 3,17."""
    sheet = _gabled_35(house)
    t = cfg.sheet.roof.thickness_m
    plates = _roof_plates(house_ifc(sheet, cfg))
    assert len(plates) >= 2
    for tops, bottoms in plates:
        assert all(top - bottom == pytest.approx(t, abs=1e-5) for top, bottom in zip(
            tops, bottoms, strict=True))
    edge = 3.25 - 0.4 * math.tan(math.radians(35))
    assert min(b for _, bottoms in plates for b in bottoms) == pytest.approx(edge, abs=1e-3)
    assert min(t_ for tops, _ in plates for t_ in tops) == pytest.approx(edge + t, abs=1e-3)


def test_sheet_ifc_and_3d_take_one_roof_thickness(house, cfg, tmp_path):
    """Одно значение `[roof] thickness_m` листа: поменяли в настройках — меняется и полоса кровли
    на листе, и плита в IFC, и толщина в данных 3D."""
    sheet = _gabled_35(house)
    (tmp_path / "sheet.toml").write_text("[roof]\nthickness_m = 0.35\n")
    thick = config.load(tmp_path)
    assert thick.sheet.roof.thickness_m == 0.35 != cfg.sheet.roof.thickness_m
    for conf, t in ((cfg, cfg.sheet.roof.thickness_m), (thick, 0.35)):
        plates = _roof_plates(house_ifc(sheet, conf))
        assert all(top - bottom == pytest.approx(t, abs=1e-5)
                   for tops, bottoms in plates for top, bottom in zip(tops, bottoms, strict=True))
        assert house_3d(sheet, conf)["roof"]["thickness_m"] == t
    assert sheet_svg(sheet, cfg) != sheet_svg(sheet, thick)
