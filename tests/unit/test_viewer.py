"""Сервер смотрелки: список планов, запуск по плану, трасса, кэш страницы."""

import re

import pytest
from fastapi.testclient import TestClient
from simple_house import SIMPLE

from genfacade import config
from genfacade.datasets import store
from genfacade.render.svg import sheet_svg
from genfacade.schema import ElementClass, Mode, VariantKind, ZoneRole
from genfacade.train import tokens
from genfacade.viewer.app import STATIC, create_app

PLAN_RUN = {"plan": SIMPLE.stem, "text": "A simple one-storey house.", "mode": Mode.BLIND}


@pytest.fixture
def client(tmp_path):
    (tmp_path / "viewer.toml").write_text(
        f'[paths]\nruns_dir = "{tmp_path / "runs"}"\nplans_dirs = ["{SIMPLE.parent}"]\n'
        "[samples]\nshown = 2\n")
    (tmp_path / "data.toml").write_text(f'[paths]\nsamples_dir = "{tmp_path / "samples"}"\n')
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


def test_no_samples_no_sources(client):
    assert client.get("/api/samples").json() == []


def test_samples_listed_by_source(client, sample, tmp_path):
    """Вкладка «Датасеты»: первые `shown` примеров источника и опись по всем."""
    for name in ("c", "a", "b"):
        store.write(sample.model_copy(update={"id": name}), tmp_path / "samples")
    [found] = client.get("/api/samples").json()
    assert (found["source"], found["ids"]) == (sample.source, ["a", "b"])
    assert (found["samples"], found["walls"], found["splits"]) == (3, 12, {sample.split: 3})
    assert set(found["elements"]) <= set(client.get("/api/options").json()["cls"])


def test_sample_thumbnail_is_its_sheet(client, sample, tmp_path, cfg):
    store.write(sample, tmp_path / "samples")
    res = client.get(f"/api/samples/{sample.source}/{sample.id}/sheet.svg")
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert res.text.count("data-cls") == sheet_svg(sample.sheet, cfg).count("data-cls") > 0
    assert client.get(f"/api/samples/{sample.source}/nope/sheet.svg").status_code == 404


@pytest.fixture
def opened(client, tmp_path):
    """Записать пример и открыть его в смотрелке → (имя папки просмотра, её meta)."""
    def open_(sample) -> tuple[str, dict]:
        store.write(sample, tmp_path / "samples")
        run_id = client.post(f"/api/samples/{sample.source}/{sample.id}").json()["id"]
        return run_id, client.get(f"/api/runs/{run_id}").json()

    return open_


def test_sample_opens_as_plan_tokens_and_sheet(client, sample, opened):
    """Пример открывается тем же экраном, что прогон; в список прогонов не попадает."""
    run_id, meta = opened(sample)
    assert [s["n"] for s in meta["steps"]] == [2, 4, 6] and "input" not in meta
    assert meta["sample"]["split"] == sample.split
    for step in meta["steps"]:
        expected = "<house>" if step["file"] == meta["tokens"] else "<svg"
        assert expected in client.get(f"/files/{run_id}/{step['file']}").text, step
    assert client.get("/api/runs").json() == []


def test_sample_tokens_shown_for_every_mode(client, sample, opened, cfg):
    """Шаг «Токены»: по режиму — условие и ответ; строки складываются в ту же цепочку."""
    run_id, meta = opened(sample)
    shown = client.get(f"/files/{run_id}/{meta['tokens']}").json()
    assert set(shown) == set(Mode)
    for mode in Mode:
        given, answer = shown[mode]
        assert " ".join(given["lines"]).split() == tokens.condition(sample.sheet, mode, cfg)
        assert " ".join(answer["lines"]).split() == tokens.answer(sample.sheet, mode, cfg)
        assert answer["count"] == len(tokens.answer(sample.sheet, mode, cfg))
        # своя строка — у <answer>, каждой стены, каждого элемента и зоны, и у <end>
        walls = sample.sheet.facades
        rows = 2 + len(walls) + sum(len(f.elements) + len(f.zones) for f in walls)
        assert len(answer["lines"]) == rows


def test_sample_that_cannot_be_tokenized_opens_without_tokens(sample, opened):
    """Дом со стилем не из словаря: план и лист открываются, шага «Токены» нет."""
    odd = sample.sheet.spec.model_copy(update={"style": "gothic"})
    _, meta = opened(sample.model_copy(update={
        "sheet": sample.sheet.model_copy(update={"spec": odd})}))
    assert [s["n"] for s in meta["steps"]] == [2, 6] and meta["tokens"] is None


def test_unknown_sample_and_source(client):
    assert client.post("/api/samples/synthetic/nope").status_code == 404
    assert client.post("/api/samples/nope/simple_house").status_code == 422
