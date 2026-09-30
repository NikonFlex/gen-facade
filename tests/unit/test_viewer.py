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
