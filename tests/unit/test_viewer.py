from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from genfacade import config
from genfacade.viewer.app import create_app


@pytest.fixture
def client(tmp_path):
    fixtures = Path(__file__).resolve().parents[1] / "fixtures"
    (tmp_path / "viewer.toml").write_text(
        f'[paths]\nruns_dir = "{tmp_path / "runs"}"\nhouses_dirs = ["{fixtures}"]\n')
    return TestClient(create_app(config.load(tmp_path)))


def test_houses_listed(client):
    names = [h["name"] for h in client.get("/api/houses").json()]
    assert names == ["house_flat", "house_gable", "house_hip"]


def test_run_house_and_read_trace(client):
    run_id = client.post("/api/runs", json={"house": "house_hip"}).json()["id"]
    assert [r["id"] for r in client.get("/api/runs").json()] == [run_id]
    meta = client.get(f"/api/runs/{run_id}").json()
    sheet = next(s for s in meta["steps"] if s["n"] == 6)
    svg = client.get(f"/files/{run_id}/{sheet['file']}")
    assert svg.status_code == 200 and "data-cls" in svg.text


def test_run_sent_json(client, raw_house):
    raw_house["spec"]["floors"] = 2
    raw_house["spec"]["floor_heights_m"] = [2.8, 2.7]
    res = client.post("/api/runs", json={"sheet": raw_house, "name": "двухэтажный"})
    assert res.status_code == 200


def test_invalid_json_explained(client, raw_house):
    raw_house["spec"]["floors"] = 3
    res = client.post("/api/runs", json={"sheet": raw_house})
    assert res.status_code == 422 and "floor_heights_m" in res.text


def test_unknown_house_and_run(client):
    assert client.post("/api/runs", json={"house": "nope"}).status_code == 404
    assert client.get("/api/runs/..%2F..%2Fetc").status_code == 404


def test_page_served(client):
    assert "смотрелка" in client.get("/").text


def test_page_and_static_revalidated(client):
    # Без этого браузер держит старый app.js при новом index.html — кнопки ломаются.
    for path in ("/", "/static/app.js", "/static/style.css", "/static/stage.js"):
        assert client.get(path).headers["cache-control"] == "no-cache", path


PLAN_RUN = {"plan": "house", "text": "Two-storey classic house.", "mode": "blind"}


def test_plans_listed_and_served(client):
    names = [p["name"] for p in client.get("/api/plans").json()]
    assert "house" in names and "door_top" in names
    svg = client.get("/api/plans/house")
    assert svg.status_code == 200 and svg.text.startswith("<?xml")
    assert client.get("/api/plans/nope").status_code == 404


def test_plan_run_traces_every_step(client):
    run_id = client.post("/api/runs", json={"plan_run": PLAN_RUN}).json()["id"]
    meta = client.get(f"/api/runs/{run_id}").json()
    assert meta["kind"] == "plan" and all(s["file"] for s in meta["steps"])
    assert client.get(f"/files/{run_id}/{meta['plan_input']}").status_code == 200


def test_plan_run_with_sent_svg(client):
    svg = (Path(__file__).resolve().parents[1] / "fixtures" / "genplan" / "door_left.svg")
    svg = svg.read_text()
    res = client.post("/api/runs", json={"plan_run": {**PLAN_RUN, "plan": "мой план"}, "svg": svg})
    assert res.status_code == 200


def test_defective_plan_explained(client):
    bad = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    res = client.post("/api/runs", json={"plan_run": PLAN_RUN, "svg": bad})
    assert res.status_code == 400 and "план отклонён" in res.json()["detail"]
