"""Сервер смотрелки: список планов, запуск по плану, трасса, кэш страницы."""

import re

import pytest
from fastapi.testclient import TestClient
from simple_house import SIMPLE

from genfacade import config
from genfacade.schema import ElementClass, Mode, VariantKind, ZoneRole
from genfacade.viewer.app import STATIC, create_app

PLAN_RUN = {"plan": SIMPLE.stem, "text": "A simple one-storey house.", "mode": Mode.BLIND}


@pytest.fixture
def client(tmp_path):
    (tmp_path / "viewer.toml").write_text(
        f'[paths]\nruns_dir = "{tmp_path / "runs"}"\nplans_dirs = ["{SIMPLE.parent}"]\n')
    return TestClient(create_app(config.load(tmp_path)))


def test_page_served(client):
    assert "смотрелка" in client.get("/").text


def test_page_and_static_revalidated(client):
    # Без этого браузер держит старый app.js при новом index.html — кнопки ломаются.
    for path in ("/", "/static/app.js", "/static/style.css", "/static/stage.js"):
        assert client.get(path).headers["cache-control"] == "no-cache", path


def test_options_label_every_enum_value(client):
    """Режимы и подписи страница берёт с сервера: у каждого значения enum есть подпись."""
    options = client.get("/api/options").json()
    assert [m["value"] for m in options["modes"]] == list(Mode)
    assert all(m["title"] and m["hint"] for m in options["modes"])
    assert options["default_mode"] in list(Mode)
    for key, enum in (("cls", ElementClass), ("role", ZoneRole), ("variant", VariantKind)):
        assert set(options[key]) == set(enum), key
        assert all(options[key].values()), key


def test_page_does_not_repeat_enum_values():
    """Одно значение — в одном месте: в JS и HTML значений enum из schema.py нет."""
    values = [*Mode, *ElementClass, *VariantKind, *ZoneRole]
    quoted = re.compile("[\"'`](" + "|".join(map(re.escape, values)) + ")[\"'`]")
    key = re.compile(r"\b(" + "|".join(map(re.escape, values)) + r"):")
    for name in ("app.js", "stage.js"):
        text = STATIC.joinpath(name).read_text()
        assert not quoted.findall(text) and not key.findall(text), name
    html = STATIC.joinpath("index.html").read_text()
    assert not re.findall('value="(' + "|".join(Mode) + ')"', html)


def test_one_plan_listed_and_served(client):
    assert client.get("/api/plans").json() == [{"name": SIMPLE.stem}]
    svg = client.get(f"/api/plans/{SIMPLE.stem}")
    assert svg.status_code == 200 and svg.text.startswith("<?xml")
    assert client.get("/api/plans/nope").status_code == 404


def test_plan_run_traces_every_step(client):
    run_id = client.post("/api/runs", json={"plan_run": PLAN_RUN}).json()["id"]
    assert [r["id"] for r in client.get("/api/runs").json()] == [run_id]
    meta = client.get(f"/api/runs/{run_id}").json()
    assert all(s["file"] for s in meta["steps"]) and meta["errors"] == 0
    assert client.get(f"/files/{run_id}/{meta['plan_input']}").status_code == 200
    sheet = next(s for s in meta["steps"] if s["n"] == 6)
    assert "data-cls" in client.get(f"/files/{run_id}/{sheet['file']}").text


def test_plan_run_with_sent_svg(client):
    svg = SIMPLE.read_text()
    res = client.post("/api/runs", json={"plan_run": {**PLAN_RUN, "plan": "мой план"}, "svg": svg})
    assert res.status_code == 200


def test_unknown_plan_and_run(client):
    missing = {"plan_run": {**PLAN_RUN, "plan": "nope"}}
    assert client.post("/api/runs", json=missing).status_code == 404
    assert client.get("/api/runs/nope").status_code == 404


def test_defective_plan_explained(client):
    bad = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    res = client.post("/api/runs", json={"plan_run": PLAN_RUN, "svg": bad})
    assert res.status_code == 400 and "план отклонён" in res.json()["detail"]
