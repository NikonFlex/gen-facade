"""Страница правки разметки /markup (gf#348, `data: Правка разметки в браузере`): рамка, сдвинутая в
браузере, пишется в TOML того же формата, `genfacade manual` собирает его без правок; состояние
дома — хранимое поле очереди с таблицей переходов; время на дом и счёт — в файле очереди."""

import itertools
import json
import socket
import threading
import tomllib
from importlib.util import find_spec
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from genfacade import config
from genfacade.datasets import manual, markup_edit, markup_toml, store
from genfacade.schema import (
    CheckState,
    DormerRoof,
    ElementClass,
    LevelKind,
    MarkKind,
    PaletteRole,
    Refusal,
    Refused,
    RejectReason,
    RoofKind,
    Source,
)
from genfacade.viewer import markup_queue
from genfacade.viewer.app import create_app

HOUSE = "st-test"
PAGE = (1440, 1080)
PT_PER_M = 100.0
FLOOR = 800.0
WINDOW = [300.0, 560.0, 420.0, 700.0]   # окно 1,2 × 1,4 м на первой стороне


def side(view: str, page: int, length_m: float, *elements: dict) -> dict:
    left = 200.0
    return {"view": view, "page": page, "wall": [left, left + length_m * PT_PER_M],
            "floor": FLOOR, "elements": list(elements)}


RAW = {
    "id": HOUSE, "pdf": "test/sheet.pdf", "roof": "вальмовая 22°", "roof_kind": "hip",
    "pitch_deg": 22.0, "overhang_m": 0.5, "unit": "m", "pt_per_unit": PT_PER_M,
    "material": "siding", "plinth": 0.4,
    "floor_heights": [2.8], "cut": ["south: крыльцо не размечено"],
    "sides": [side("Фасад юг", 1, 10, {"cls": "window", "box": WINDOW},
                   {"cls": "door", "box": [700.0, 520.0, 800.0, 800.0]}),
              side("Фасад запад", 2, 8, {"cls": "window", "box": [400.0, 560.0, 520.0, 700.0]}),
              side("Фасад север", 3, 10), side("Фасад восток", 4, 8)],
}


def make_cfg(root: Path) -> config.Config:
    """Настройки с папкой разметки, листами, кэшем и примерами дома под tmp."""
    cfg = config.load()
    paths = cfg.data.manual.paths.model_copy(update={
        "markup_dir": root / "markup", "pdf_dirs": {"stroim": root / "pdf"}})
    manual_rules = cfg.data.manual.model_copy(update={"paths": paths})
    data = cfg.data.model_copy(update={
        "manual": manual_rules,
        "paths": cfg.data.paths.model_copy(update={"samples_dir": root / "samples"})})
    editor = cfg.viewer.markup.model_copy(update={
        "folder": root / "markup" / "stroim", "cache_dir": root / "cache"})
    viewer = cfg.viewer.model_copy(update={
        "markup": editor, "paths": cfg.viewer.paths.model_copy(update={"runs_dir": root / "runs"})})
    return cfg.model_copy(update={"data": data, "viewer": viewer})


@pytest.fixture
def cfg(tmp_path) -> config.Config:
    folder = tmp_path / "markup" / "stroim"
    folder.mkdir(parents=True)
    head = "# Тестовый дом: шапка с происхождением должна пережить правку\n"
    (folder / f"{HOUSE}.toml").write_text(
        markup_toml.dumps(manual.Markup.model_validate(RAW), head.strip()))
    (tmp_path / "pdf" / "test").mkdir(parents=True)
    pages = [Image.new("RGB", PAGE, shade) for shade in ("white", "ivory", "azure", "linen")]
    pages[0].save(tmp_path / "pdf" / "test" / "sheet.pdf", save_all=True, append_images=pages[1:])
    return make_cfg(tmp_path)


@pytest.fixture
def client(cfg) -> TestClient:
    return TestClient(create_app(cfg))


def window_x(cfg: config.Config) -> float:
    """x окна южной стороны в метрах — так, как собрал бы его `genfacade manual`."""
    manual.run(cfg)
    sheet = store.read(cfg.data.paths.samples_dir, Source.MANUAL, HOUSE).sheet
    windows = [e for e in sheet.facades[0].elements if e.cls is ElementClass.WINDOW]
    return windows[0].x_m


def edit_body(client: TestClient, box: list[float]) -> dict:
    """Правка как её присылает страница: все стороны, у первой окно на новом месте."""
    opened = client.post(f"/api/markup/{HOUSE}/open").json()
    sides = [{"wall": s["wall"], "pt_per_unit": s["geometry"]["pt_per_unit"],
              "elements": s["elements"]} for s in opened["sides"]]
    sides[0]["elements"][0]["box"] = box
    return {"sides": sides, "levels": []}


def roof_edit(client: TestClient, house: dict | None = None, **marks: list) -> dict:
    """Правка как со страницы: рамки на месте, поля дома — как открыты, поверх — house и отметки."""
    body = edit_body(client, WINDOW)
    opened = client.post(f"/api/markup/{HOUSE}/open").json()["house"]
    return {**body, "house": {**opened, **(house or {})}, **marks}


def save_edit(client: TestClient, body: dict) -> None:
    """«Сохранить правку»: дом поправлен и собирается в пример, как в `genfacade manual`."""
    got = client.post(f"/api/markup/{HOUSE}/decision", json={"good": True, "edit": body}).json()
    assert got["state"] == CheckState.EDITED and got["assembly"] == {"ok": True, "detail": ""}


def test_markup_toml_roundtrips_every_real_markup():
    for path in sorted(Path("markup").glob("*/*.toml")):
        m = manual.read(path)
        text = markup_toml.dumps(m, markup_toml.header(path.read_text()))
        assert manual.Markup.model_validate(tomllib.loads(text)) == m, path


def test_queue_starts_unchecked_and_counts(client, cfg):
    got = client.get("/api/markup").json()
    assert [(i["id"], i["state"]) for i in got["items"]] == [(HOUSE, CheckState.UNCHECKED)]
    assert got["counts"] == {"total": 1, "checked": 0, "left": 1, "median_seconds": None}
    assert got["next"] == HOUSE
    # состояние — хранимое поле файла очереди, а не вывод из наличия разметки
    saved = json.loads((cfg.viewer.markup.folder / cfg.viewer.markup.state_file).read_text())
    assert saved["houses"][HOUSE]["state"] == CheckState.UNCHECKED


def test_open_returns_boxes_in_sheet_points_and_image(client):
    got = client.post(f"/api/markup/{HOUSE}/open").json()
    first = got["sides"][0]
    assert first["elements"][0]["box"] == WINDOW
    assert first["size"] == [PAGE[0], PAGE[1]]
    assert first["geometry"]["px_per_m"] == PT_PER_M
    assert first["geometry"]["ground"] == FLOOR + 0.4 * PT_PER_M
    assert first["geometry"]["tops"] == [FLOOR - 2.8 * PT_PER_M]
    image = client.get(first["image"])
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/jpeg"


def test_good_without_edit_marks_house_good_and_keeps_file(client, cfg):
    path = cfg.viewer.markup.folder / f"{HOUSE}.toml"
    before = path.read_text()
    client.post(f"/api/markup/{HOUSE}/open")
    got = client.post(f"/api/markup/{HOUSE}/decision", json={"good": True}).json()
    assert got["state"] == CheckState.GOOD
    assert got["seconds"] >= 0 and got["next"] is None
    assert got["counts"]["checked"] == 1 and got["counts"]["left"] == 0
    assert path.read_text() == before
    assert not (cfg.viewer.markup.folder / cfg.viewer.markup.original_dir).exists()


def test_moved_box_is_saved_to_toml_and_assembled_by_manual(client, cfg):
    path = cfg.viewer.markup.folder / f"{HOUSE}.toml"
    before, original = window_x(cfg), path.read_text()
    moved = [WINDOW[0] + 150.0, WINDOW[1], WINDOW[2] + 150.0, WINDOW[3]]   # на 1,5 м вправо
    save_edit(client, edit_body(client, moved))
    saved = manual.read(path)
    assert list(saved.sides[0].elements[0].box) == moved
    assert path.read_text().startswith("# Тестовый дом")   # шапка с происхождением сохранена
    assert (cfg.viewer.markup.folder / "orig" / path.name).read_text() == original
    assert window_x(cfg) == pytest.approx(before + 1.5, abs=0.01)   # окно собрано на новом месте
    reopened = client.post(f"/api/markup/{HOUSE}/open").json()
    assert reopened["state"] == CheckState.EDITED
    assert reopened["sides"][0]["elements"][0]["box"] == moved


def test_edit_without_changes_is_not_an_edit(client):
    body = edit_body(client, WINDOW)
    got = client.post(f"/api/markup/{HOUSE}/decision", json={"good": True, "edit": body}).json()
    assert got["state"] == CheckState.GOOD


def test_rejection_needs_a_reason_from_the_list(client):
    bad = client.post(f"/api/markup/{HOUSE}/decision", json={"good": False})
    assert bad.status_code == 422
    unknown = client.post(f"/api/markup/{HOUSE}/decision", json={"good": False, "reason": "boring"})
    assert unknown.status_code == 422
    got = client.post(f"/api/markup/{HOUSE}/decision",
                      json={"good": False, "reason": RejectReason.BAD_SCALE, "note": "нет"})
    assert got.json()["state"] == CheckState.REJECTED
    item = client.get("/api/markup").json()["items"][0]
    assert (item["state"], item["reason"]) == (CheckState.REJECTED, RejectReason.BAD_SCALE)


def test_unknown_house_and_broken_edit_are_refusals_with_codes(client):
    missing = client.post("/api/markup/st-nope/open")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == Refusal.NO_MARKUP_HOUSE
    body = edit_body(client, WINDOW)
    body["sides"][1]["elements"][0]["parent"] = 7   # родителя с таким номером нет
    bad = client.post(f"/api/markup/{HOUSE}/decision", json={"good": True, "edit": body})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == Refusal.BAD_MARKUP_EDIT
    assert client.get("/api/markup").json()["items"][0]["state"] == CheckState.UNCHECKED
    body["sides"].pop()
    assert client.post(f"/api/markup/{HOUSE}/preview", json=body).status_code == 422


def test_dragged_levels_are_recomputed_for_every_side_by_the_server(client):
    body = edit_body(client, WINDOW)
    eaves = FLOOR - 3.0 * PT_PER_M   # карниз потянули на высоту 3,0 м
    body["levels"] = [{"side": 0, "kind": LevelKind.TOP, "index": 0, "y": eaves},
                      {"side": 0, "kind": LevelKind.GROUND, "y": FLOOR + 0.5 * PT_PER_M}]
    got = client.post(f"/api/markup/{HOUSE}/preview", json=body).json()["geometry"]
    assert [g["tops"] for g in got] == [[eaves]] * 4   # высота общая для всех сторон дома
    assert {g["ground"] for g in got} == {FLOOR + 0.5 * PT_PER_M}
    saved = client.post(f"/api/markup/{HOUSE}/decision", json={"good": True, "edit": body}).json()
    assert saved["state"] == CheckState.EDITED


def test_roof_pitch_and_chimney_are_saved_to_toml_and_open_again(client, cfg):
    path = cfg.viewer.markup.folder / f"{HOUSE}.toml"
    assert manual.read(path).chimneys == []
    chimney = {"side": 0, "x": 450.0}   # на виде южной стены: сторона 0
    body = roof_edit(client, {"pitch_deg": 30.0}, chimneys=[chimney])
    save_edit(client, body)
    saved = manual.read(path)
    assert saved.pitch_deg == 30.0 and saved.roof_kind is RoofKind.HIP
    assert [c.model_dump(mode="json", exclude_none=True) for c in saved.chimneys] == [chimney]
    assert "pitch_deg = 30.0" in path.read_text()
    reopened = client.post(f"/api/markup/{HOUSE}/open").json()
    assert reopened["house"]["pitch_deg"] == 30.0
    assert [s["marks"][MarkKind.CHIMNEY] for s in reopened["sides"]] == [
        [chimney | {"depth_m": None}], [], [], []]  # вынос не задан — null


def test_edit_keeps_marks_it_does_not_send_and_erases_an_empty_list(client, cfg):
    path = cfg.viewer.markup.folder / f"{HOUSE}.toml"
    skylight = {"side": 1, "x": [250.0, 330.0], "y": [450.0, 570.0]}
    client.post(f"/api/markup/{HOUSE}/decision", json={"good": True, "edit": roof_edit(
        client, chimneys=[{"side": 0, "x": 450.0}], skylights=[skylight])})
    client.post(f"/api/markup/{HOUSE}/decision", json={"good": True, "edit": roof_edit(
        client, chimneys=[])})
    saved = manual.read(path)
    kept = [s.model_dump(mode="json") for s in saved.skylights]
    assert saved.chimneys == [] and kept == [skylight]


def refused(client: TestClient, cfg, body: dict) -> None:
    """Правка отвергнута кодом BAD_MARKUP_EDIT, файл не менялся, дом не «поправлен»."""
    path = cfg.viewer.markup.folder / f"{HOUSE}.toml"
    before = path.read_text()
    bad = client.post(f"/api/markup/{HOUSE}/decision", json={"good": True, "edit": body})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == Refusal.BAD_MARKUP_EDIT
    assert path.read_text() == before
    assert client.get("/api/markup").json()["items"][0]["state"] == CheckState.UNCHECKED


@pytest.mark.parametrize("house, marks", [
    ({"pitch_deg": 95.0}, {}),                                    # уклон вне диапазона
    ({"roof_kind": RoofKind.FLAT, "pitch_deg": 30.0}, {}),        # плоская с уклоном
    ({"roof_material": "no-such-roof"}, {}),                      # вид не из library.toml
    ({"material": "no-such-wall"}, {}),
    ({"trim": {"casing": "no-such-casing"}}, {}),                 # вид не из derive.toml
    ({}, {"chimneys": [{"side": 9, "x": 1.0}]}),                  # такой стороны нет
])
def test_impossible_roof_edit_is_refused_by_code_and_file_stays(client, cfg, house, marks):
    refused(client, cfg, roof_edit(client, house, **marks))


ZONE = {"role": "accent", "material": "brick", "box": [320.0, 420.0, 520.0, 560.0]}  # юг


def zone_edit(client: TestClient, zones: list[dict], house: dict | None = None) -> dict:
    """Правка как со страницы: у южной стороны зоны второй отделки, остальное — как открыто."""
    body = roof_edit(client, house)
    body["sides"][0]["zones"] = zones
    return body


def test_zone_drawn_on_south_view_is_saved_as_the_only_second_finish(client, cfg):
    path = cfg.viewer.markup.folder / f"{HOUSE}.toml"
    assert all(not e.zones for e in manual.read(path).sides)
    save_edit(client, zone_edit(client, [ZONE]))
    saved = manual.read(path)
    zones = [[z.model_dump(mode="json") for z in e.zones] for e in saved.sides]
    assert zones == [[ZONE], [], [], []]
    reopened = client.post(f"/api/markup/{HOUSE}/open").json()
    assert reopened["house"]["second_material"] == "brick"
    assert PaletteRole.ACCENT in reopened["roles"]
    assert client.get("/api/markup").json()["items"][0]["state"] == CheckState.EDITED


def test_second_material_field_gives_its_kind_to_every_zone(client, cfg):
    save_edit(client, zone_edit(client, [ZONE], {"second_material": "stone"}))
    assert {z.material for e in manual.read(
        cfg.viewer.markup.folder / f"{HOUSE}.toml").sides for z in e.zones} == {"stone"}


def test_zones_not_sent_stay_and_an_empty_list_erases_them(client, cfg):
    path = cfg.viewer.markup.folder / f"{HOUSE}.toml"
    save_edit(client, zone_edit(client, [ZONE]))
    save_edit(client, roof_edit(client, {"pitch_deg": 30.0}))   # зон в запросе нет
    assert len(manual.read(path).sides[0].zones) == 1
    save_edit(client, zone_edit(client, []))
    assert all(not e.zones for e in manual.read(path).sides)


def test_accent_color_is_saved_and_unset_color_is_removed(client, cfg):
    path = cfg.viewer.markup.folder / f"{HOUSE}.toml"
    save_edit(client, zone_edit(client, [ZONE], {"colors": {"accent": "#a04030"}}))
    assert manual.read(path).colors == {PaletteRole.ACCENT: "#a04030"}
    assert 'accent = "#a04030"' in path.read_text()
    save_edit(client, roof_edit(client, {"colors": {}}))
    assert manual.read(path).colors == {}


def test_preview_gives_palette_roles_of_the_edited_house(client):
    got = client.post(f"/api/markup/{HOUSE}/preview", json=zone_edit(client, [ZONE])).json()
    assert PaletteRole.ACCENT in got["roles"] and PaletteRole.MAIN in got["roles"]
    plain = client.post(f"/api/markup/{HOUSE}/preview", json=roof_edit(client)).json()
    assert PaletteRole.ACCENT not in plain["roles"]


def test_two_second_finishes_are_refused(client, cfg):
    second = {**ZONE, "material": "stone"}
    refused(client, cfg, zone_edit(client, [ZONE, second]))


def test_second_finish_not_from_the_library_is_refused(client, cfg):
    refused(client, cfg, zone_edit(client, [{**ZONE, "material": "no-such-wall"}]))


@pytest.mark.parametrize("colors", [{"accent": "#a04030"}, {"main": "#zzz"}, {"main": "red"}])
def test_color_of_a_role_without_material_or_not_hex_is_refused(client, cfg, colors):
    refused(client, cfg, roof_edit(client, {"colors": colors}))


def test_page_options_give_every_choice_the_fields_need(client, cfg):
    got = client.get("/api/markup").json()["options"]
    assert got["choices"] == {"roof_kind": list(RoofKind), "dormer_roof": list(DormerRoof)}
    form = {r["name"]: r for r in got["house_form"]}
    assert form["roof_material"]["choices"] == sorted(cfg.library.kinds)
    assert form["trim.casing"]["choices"] == cfg.derive.kinds("casing")
    assert form["trim.door"]["empty"] and not form["roof_kind"]["empty"]
    assert set(form) == set(cfg.viewer.markup.labels.house)
    assert {k: v["field"] for k, v in got["marks"].items()} == markup_edit.MARK_FIELDS


def test_every_pair_of_states_follows_the_transition_table():
    for old, new in itertools.product(CheckState, CheckState):
        rec = markup_queue.Record(
            state=old, reason=RejectReason.OTHER if old is CheckState.REJECTED else None)
        reason = RejectReason.OTHER if new is CheckState.REJECTED else None
        if new in markup_queue.TRANSITIONS[old]:
            assert markup_queue.transition(rec, new, reason, "", 100.0).state is new
        else:
            with pytest.raises(Refused) as err:
                markup_queue.transition(rec, new, reason, "", 100.0)
            assert err.value.code is Refusal.BAD_CHECK_STEP
    # сама таблица: поправленный дом не становится «хорошо», в «не проверен» не возвращаются
    good, edited, rejected = CheckState.GOOD, CheckState.EDITED, CheckState.REJECTED
    assert markup_queue.TRANSITIONS == {
        CheckState.UNCHECKED: {good, edited, rejected}, good: {good, edited, rejected},
        edited: {edited, rejected}, rejected: {good, edited, rejected}}


def test_seconds_are_counted_from_the_last_open_to_the_decision():
    rec = markup_queue.Record(opened_at=100.0)
    done = markup_queue.transition(rec, CheckState.GOOD, None, "", 112.46)
    assert done.seconds == 12.5
    assert markup_queue.counts({"a": done, "b": markup_queue.Record()}) == {
        "total": 2, "checked": 1, "left": 1, "median_seconds": 12.5}


def test_broken_state_file_is_a_refusal_not_an_empty_queue(client, cfg):
    (cfg.viewer.markup.folder / cfg.viewer.markup.state_file).write_text("{")
    got = client.get("/api/markup")
    assert got.status_code == 500 and got.json()["detail"]["code"] == Refusal.BAD_CHECK_STATE


def test_level_lines_roundtrip_through_the_markup_model():
    m = manual.Markup.model_validate(RAW)
    e = m.sides[0]
    assert m.with_ground(e, m.ground_y(e) + 20).plinth == pytest.approx(0.6)
    assert m.with_top(e, 0, m.tops_y(e)[0] - 30).floor_heights == [pytest.approx(3.1)]
    assert markup_edit.geometry(m, 0)["px_per_m"] == PT_PER_M


# ——— браузер: рамку двигают мышью ———

needs_browser = pytest.mark.skipif(find_spec("playwright") is None,
                                   reason="нет playwright: CI и dev без браузера")


@pytest.fixture
def server(cfg):
    """Смотрелка на свободном порту 127.0.0.1 — только эта машина."""
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port,
                                        log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        thread.join(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(10)


@needs_browser
def test_box_dragged_in_browser_is_saved_and_assembled(server, cfg):
    from playwright import sync_api

    path = cfg.viewer.markup.folder / f"{HOUSE}.toml"
    before = window_x(cfg)
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-proxy-server"])
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.set_default_timeout(120000)
        page.goto(f"{server}/markup#h={HOUSE}")
        page.wait_for_selector(".mk-view rect.box")
        view = page.locator(".mk-view").first
        scale = view.evaluate("(v) => v.getBoundingClientRect().width / v.viewBox.baseVal.width")
        rect = view.locator("rect.box").first.bounding_box()
        x, y = rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 40, y, steps=5)
        page.mouse.move(x + 90, y, steps=5)
        page.mouse.up()
        assert page.locator("#good").inner_text() == "Сохранить правку"
        page.locator("#good").click()
        page.wait_for_function("() => document.querySelector('.toast')")
        browser.close()
    shift = manual.read(path).sides[0].elements[0].box[0] - WINDOW[0]
    assert shift == pytest.approx(90 / scale, abs=1.0)
    assert window_x(cfg) == pytest.approx(before + shift / PT_PER_M, abs=0.01)
    state = json.loads((cfg.viewer.markup.folder / cfg.viewer.markup.state_file).read_text())
    assert state["houses"][HOUSE]["state"] == CheckState.EDITED
    assert state["houses"][HOUSE]["seconds"] > 0
