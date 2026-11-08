"""Вкладка «Каталог» смотрелки (gf#354): состав — из конфига и схемы, картинка — тем же
render/svg.py, что лист. Без сценария спеки: это просмотр, не поведение модуля."""

import re

import pytest
from fastapi.testclient import TestClient

from genfacade import config
from genfacade.schema import DOOR_KINDS, Refusal, RoofKind, Trim, VariantKind
from genfacade.viewer import catalog, catalog_doc, samples
from genfacade.viewer.app import STATIC, create_app

NEW_KINDS = (
    '[kinds]\nmarble = "#e0e0e8"\nslate_roof = "#2b2f36"\n'
    "[patterns.marble]\nvertical = false\nline_m = 0.01\ngroove_m = 0.0\nwidth_m = 0.6\n"
    "courses = [{ h_m = 0.3, joints_m = [0.3] }]\n")
NEW_FINISH = """
[spec.colors.test_blue]
hex = "#3355aa"
words = ["lapis"]
[spec.finish.test_slate]
styles = ["modern"]
roof = "gable"
trim = { sill = "flat", casing = "none", shutters = "none", canopy = "flat" }
[spec.finish.test_slate.materials]
main = { kind = "marble", colors = ["test_blue"] }
plinth = { kind = "concrete", colors = ["concrete"] }
accent = { kind = "wood", colors = ["wood_natural"] }
trim = { kind = "metal", colors = ["graphite"] }
roof = { kind = "slate_roof", colors = ["test_blue"] }
"""


def client_for(tmp_path, *folders) -> TestClient:
    (tmp_path / "viewer.toml").write_text(f'[paths]\nruns_dir = "{tmp_path / "runs"}"\n')
    return TestClient(create_app(config.load(tmp_path, *folders)))


@pytest.fixture
def client(tmp_path):
    return client_for(tmp_path)


def count(client: TestClient) -> dict[str, int]:
    return {s["id"]: s["count"] for s in client.get("/api/catalog").json()["sections"]}


def names(client: TestClient, section: str) -> list[str]:
    found = next(s for s in client.get("/api/catalog").json()["sections"] if s["id"] == section)
    return [i["name"] for i in found["items"]]


def test_counts_match_config(client, cfg):
    """Датчик gf#354: разделов каталога — по записи в конфиге, видов в разделе — по числу видов
    в конфиге и схеме."""
    spec = cfg.models.spec
    got = count(client)
    assert list(got) == list(cfg.viewer.catalog.sections)
    assert got["colors"] == len(spec.colors)
    assert got["schemes"] == len(spec.schemes)
    assert got["finishes"] == len(spec.finish)
    assert got["roofs"] == len(RoofKind)
    assert got["windows"] == len([k for k in VariantKind if k not in DOOR_KINDS])
    assert got["doors"] == len(DOOR_KINDS) + 1 + len(catalog.derive_kinds(cfg, "door"))
    for section, trim in (("sills", Trim.SILL), ("casings", Trim.CASING),
                          ("shutters", Trim.SHUTTERS), ("canopies", Trim.CANOPY)):
        assert got[section] == len(catalog.derive_kinds(cfg, trim)) > 0
    # у каждого вида материала — своя картинка: вид попадает в стены, в кровлю или в оба
    assert set(names(client, "walls")) | set(names(client, "roofing")) == set(cfg.library.kinds)


def test_every_item_is_drawn(client):
    """Каждый вид из выдачи рисуется: картинка по адресу из выдачи — SVG."""
    for section in client.get("/api/catalog").json()["sections"]:
        for item in section["items"]:
            res = client.get(item["image"])
            assert res.status_code == 200, item["image"]
            assert res.headers["content-type"] == "image/svg+xml"
            assert res.text.startswith("<svg"), item["image"]


def test_new_kind_added_by_records_appears(tmp_path, client):
    """Вид, добавленный записью во временную копию конфига, появляется в каталоге без правки кода
    и страницы: материал стен, кровли, цвет и отделка."""
    assert "marble" not in names(client, "walls")
    folder = tmp_path / "extra"
    folder.mkdir()
    (folder / "library.toml").write_text(NEW_KINDS)
    (folder / "models.toml").write_text(NEW_FINISH)
    own = tmp_path / "own"
    own.mkdir()
    extended = client_for(own, folder)
    assert "marble" in names(extended, "walls")
    assert "slate_roof" in names(extended, "roofing")
    assert "test_blue" in names(extended, "colors")
    assert "test_slate" in names(extended, "finishes")
    assert count(extended)["walls"] == count(client)["walls"] + 1
    for section, name in (("walls", "marble"), ("roofing", "slate_roof"),
                          ("finishes", "test_slate"), ("colors", "test_blue")):
        assert extended.get(f"/api/catalog/{section}/{name}/image.svg").status_code == 200
    assert "hatch-marble-" in extended.get("/api/catalog/walls/marble/image.svg").text


def test_words_and_source_come_from_config_and_doc(client, cfg):
    sections = {s["id"]: s for s in client.get("/api/catalog").json()["sections"]}
    brick = next(i for i in sections["walls"]["items"] if i["name"] == "brick_1_5")
    assert set(cfg.models.spec.material_words["brick_1_5"]) == set(brick["words"])
    assert set(cfg.models.spec.material_words["brick"]) == set(brick["shared"])
    assert "ГОСТ 530" in brick["source"]
    assert set(sections["sills"]["words"]) == set(cfg.models.spec.trim_words[Trim.SILL])
    gable = next(i for i in sections["roofs"]["items"] if i["name"] == RoofKind.GABLE)
    assert set(gable["words"]) == set(cfg.models.spec.roof_words[RoofKind.GABLE])


def test_unknown_item_and_not_drawn_are_refusals(client, monkeypatch):
    res = client.get("/api/catalog/walls/no_such_kind/image.svg")
    assert res.status_code == 404 and res.json()["detail"]["code"] == Refusal.NO_CATALOG_ITEM
    assert client.get("/api/catalog/nothing/brick/image.svg").status_code == 404

    def broken(cfg, view):
        raise ValueError("вид не принимает схема")
    monkeypatch.setattr(samples, "render", broken)
    res = client.get("/api/catalog/walls/brick/image.svg")
    assert res.status_code == 422 and res.json()["detail"]["code"] == Refusal.CATALOG_NOT_DRAWN


def test_section_without_builder_is_an_error(tmp_path):
    (tmp_path / "viewer.toml").write_text('[catalog.sections.nowhere]\ntitle = "Нет"\n')
    with pytest.raises(ValueError, match="nowhere"):
        catalog.listing(config.load(tmp_path))


def test_doc_sources_by_heading_and_row(tmp_path):
    doc = tmp_path / "catalog.md"
    doc.write_text(
        "## Виды\n\n| Вид | Источник | Метка |\n|---|---|---|\n"
        "| `a` (было) | кирпич 250 | [открыта] |\n| наличник `flat`, `wide` | свод | x |\n"
        "| подоконник `flat` | практика | x |\n\n## Другое\n\n| Вид | Источник |\n|---|---|\n"
        "| `b` | не должен попасть |\n")
    assert catalog_doc.sources(doc, ["Виды"]) == {"a": "кирпич 250", "flat": "свод",
                                                  "wide": "свод"}
    assert catalog_doc.sources(doc, ["Виды"], "подоконник") == {"flat": "практика"}
    assert catalog_doc.sources(tmp_path / "nothing.md", ["Виды"]) == {}


def test_page_served_and_linked(client):
    page = client.get("/catalog")
    assert page.status_code == 200 and "GenFacade · каталог" in page.text
    assert page.headers["cache-control"] == "no-cache"
    # ссылка — в шапке всех страниц: разделы смотрелки перечислены в shell.js (gf#356)
    assert 'href: "/catalog"' in STATIC.joinpath("shell.js").read_text()
    assert re.search(r"/api/catalog", STATIC.joinpath("catalog.js").read_text())
