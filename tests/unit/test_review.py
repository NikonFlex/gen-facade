"""Слепая проверка листов глазами (gf#268): места строк постоянны и без названий, отметки
сохраняются со строкой, сводка считает долю принятых."""

import json

import pytest
from fastapi.testclient import TestClient

from genfacade import config
from genfacade.datasets.synthetic import build
from genfacade.metrics import calibrate
from genfacade.schema import Mode
from genfacade.viewer import review
from genfacade.viewer.app import create_app

ROWS = ("model-run1", "random", "genplan")
HOUSES = ("ffh-a", "sd-b")


@pytest.fixture
def folder(tmp_path, cfg):
    """Папка как у `genfacade realtest`: настоящие листы и три строки; у модели на sd-b — отказ."""
    sheet = build.sample(0, cfg).sheet.model_dump_json()
    refusal = json.dumps({"error": "за 5 попыток нет годного ответа"})
    for mode in Mode:
        for row in (calibrate.REFERENCE, *ROWS, "half-a"):
            (tmp_path / mode / row).mkdir(parents=True)
            for house in HOUSES:
                refused = row == ROWS[0] and house == HOUSES[1]
                text = refusal if refused else sheet
                (tmp_path / mode / row / f"{house}.json").write_text(text)
    return tmp_path


@pytest.fixture
def client(folder, tmp_path_factory):
    runs = tmp_path_factory.mktemp("runs")
    cfg_dir = tmp_path_factory.mktemp("cfg")
    (cfg_dir / "viewer.toml").write_text(f'[paths]\nruns_dir = "{runs}"\n')
    return TestClient(create_app(config.load(cfg_dir), folder))


def test_slots_hold_every_row_in_a_stable_order(folder, cfg):
    settings = cfg.viewer.review
    for mode in Mode:
        for house in HOUSES:
            order = review.slots(folder, mode, house, settings)
            assert sorted(order) == sorted(ROWS)
            assert order == review.slots(folder, mode, house, settings)   # тот же при открытии


def test_page_never_gets_row_names(client):
    """Слепая проверка: в ответе списка нет имён строк — только места и отметки."""
    data = client.get("/api/review").json()
    assert len(data["items"]) == len(Mode) * len(HOUSES)
    assert all(item["slots"] == len(ROWS) for item in data["items"])
    assert not any(row in json.dumps(data["items"]) for row in ROWS)


def test_sheets_of_reference_and_slots_are_svg(client):
    mode, house = Mode.WITH_OPENINGS, HOUSES[0]
    for slot in ("ref", "0", "1", "2"):
        got = client.get(f"/api/review/{mode}/{house}/{slot}/sheet.svg")
        assert got.status_code == 200 and got.text.startswith("<svg"), slot
    assert client.get(f"/api/review/{mode}/{house}/7/sheet.svg").status_code == 404
    assert client.get(f"/api/review/{mode}/nope/0/sheet.svg").status_code == 404


def test_houses_of_reference_and_slots_in_3d(client):
    """Хозяин 03.11: проверять по 3D-модели — у настоящего дома и у каждого места есть объём."""
    mode, house = Mode.BLIND, HOUSES[0]
    for slot in ("ref", "0", "1", "2"):
        got = client.get(f"/api/review/{mode}/{house}/{slot}/house3d")
        assert got.status_code == 200 and got.json()["walls"], slot


def test_refusal_is_shown_as_text(client, folder, cfg):
    mode, house = Mode.BLIND, HOUSES[1]
    slot = review.slots(folder, mode, house, cfg.viewer.review).index(ROWS[0])
    for view in ("sheet.svg", "house3d"):
        got = client.get(f"/api/review/{mode}/{house}/{slot}/{view}")
        assert got.status_code == 422 and "нет годного ответа" in got.json()["detail"], view


def test_marks_saved_with_row_and_counted(client, folder, cfg):
    settings = cfg.viewer.review
    for house in HOUSES:
        order = review.slots(folder, Mode.WITH_OPENINGS, house, settings)
        for slot, row in enumerate(order):
            mark = {"ok": row != "random", "why": "" if row != "random" else "окна вразнобой"}
            assert client.put(f"/api/review/{Mode.WITH_OPENINGS}/{house}/{slot}",
                              json=mark).status_code == 200
    saved = review.marks(folder)
    assert {m["row"] for m in saved.values()} == set(ROWS)
    items = client.get("/api/review").json()["items"]
    assert items[0]["marks"]["0"] is not None
    assert not any(row in json.dumps(items) for row in ROWS)       # и после отметок — вслепую
    table = review.summary(folder, settings)
    assert f"| random | {Mode.WITH_OPENINGS} | 0.00 (0/2) | 2 |" in table
    assert f"| genplan | {Mode.WITH_OPENINGS} | 1.00 (2/2) | 2 |" in table
    assert f"| genplan | {Mode.BLIND} | — | 2 |" in table


def test_mark_of_unknown_house_refused(client, folder):
    got = client.put(f"/api/review/{Mode.BLIND}/nope/0", json={"ok": True})
    assert got.status_code == 404
    assert review.marks(folder) == {}


def test_without_folder_review_is_off(tmp_path):
    (tmp_path / "viewer.toml").write_text(f'[paths]\nruns_dir = "{tmp_path / "runs"}"\n')
    client = TestClient(create_app(config.load(tmp_path)))
    assert client.get("/api/review").json() == {"folder": None, "items": []}
    assert client.get(f"/api/review/{Mode.BLIND}/x/0/sheet.svg").status_code == 404
    assert "Проверка" in client.get("/review").text


BLIND_ONLY = "levels-run1"  # строка только в папке глухого режима
MIXED = ("model-", f"{Mode.BLIND}/levels-", f"{Mode.WITH_OPENINGS}/{calibrate.REFERENCE}")


@pytest.fixture
def mixed(folder, tmp_path_factory):
    """Смешанная проверка (хозяин 04.11, gf#272): на доме — ответ модели в «окнах из плана», в
    глухом и настоящий дом, все вслепую; дома идут только по одному режиму. Строка глухого режима
    есть только в его папке, её ответ на ffh-a — отказ: по нему видно, откуда взят лист."""
    blind = folder / Mode.BLIND / BLIND_ONLY
    blind.mkdir()
    for house in HOUSES:
        (blind / f"{house}.json").write_text((folder / Mode.BLIND / ROWS[1] / f"{house}.json")
                                             .read_text())
    (blind / f"{HOUSES[0]}.json").write_text(json.dumps({"error": "глухой: нет годного ответа"}))
    cfg_dir = tmp_path_factory.mktemp("mixed")
    rows = ", ".join(f'"{r}"' for r in MIXED)
    (cfg_dir / "viewer.toml").write_text(
        f'[paths]\nruns_dir = "{tmp_path_factory.mktemp("runs")}"\n'
        f'[review]\nrows = [{rows}]\nmodes = ["{Mode.WITH_OPENINGS}"]\nreference = false\n')
    settings = config.load(cfg_dir)
    return TestClient(create_app(settings, folder)), settings.viewer.review


def test_mixed_review_shows_both_modes_and_real_house_blind(mixed, folder):
    client, settings = mixed
    mode, house = Mode.WITH_OPENINGS, HOUSES[0]
    assert review.rows(folder, mode, settings) == [
        ROWS[0], f"{Mode.BLIND}/{BLIND_ONLY}", f"{Mode.WITH_OPENINGS}/{calibrate.REFERENCE}"]
    data = client.get("/api/review").json()
    assert (data["reference"], data["modes"]) == (False, 1)
    assert {it["mode"] for it in data["items"]} == {mode}
    assert all(it["slots"] == len(MIXED) for it in data["items"])
    hidden = (ROWS[0], BLIND_ONLY, calibrate.REFERENCE)
    assert not any(r in json.dumps(data["items"]) for r in hidden)
    order = review.slots(folder, mode, house, settings)
    blind = order.index(f"{Mode.BLIND}/{BLIND_ONLY}")
    got = client.get(f"/api/review/{mode}/{house}/{blind}/sheet.svg")
    assert got.status_code == 422 and "глухой" in got.json()["detail"]
    real = order.index(f"{Mode.WITH_OPENINGS}/{calibrate.REFERENCE}")
    assert client.get(f"/api/review/{mode}/{house}/{real}/sheet.svg").text.startswith("<svg")


def test_mixed_marks_counted_per_row_and_only_its_mode(mixed, folder):
    client, settings = mixed
    mode = Mode.WITH_OPENINGS
    for house in HOUSES:
        for slot, row in enumerate(review.slots(folder, mode, house, settings)):
            mark = {"ok": row.endswith(calibrate.REFERENCE)}
            assert client.put(f"/api/review/{mode}/{house}/{slot}", json=mark).status_code == 200
    table = review.summary(folder, settings)
    assert f"| {Mode.WITH_OPENINGS}/{calibrate.REFERENCE} | {mode} | 1.00 (2/2) | 2 |" in table
    assert f"| {Mode.BLIND}/{BLIND_ONLY} | {mode} | 0.00 (0/2) | 2 |" in table
    assert {line.split("|")[2].strip() for line in table.splitlines()[2:]} == {mode}  # режим один
