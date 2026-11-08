"""Страницы «Новый дом», «Данные» и «Правила» смотрелки (gf#356). Без сценария спеки: это просмотр,
не поведение модуля. Число на странице — из конфига, форма и текст — один список слов стаба."""

import re

import pytest
from fastapi.testclient import TestClient
from simple_house import SIMPLE

from genfacade import config
from genfacade.datasets import store
from genfacade.models import spec_form, stub
from genfacade.schema import (
    ContourKind,
    DataAttr,
    Mode,
    RoofKind,
    RuleDraw,
    RuleVariant,
    Source,
    Trim,
)
from genfacade.viewer import rules
from genfacade.viewer.app import STATIC, create_app


@pytest.fixture
def cfg(tmp_path):
    (tmp_path / "viewer.toml").write_text(
        f'[paths]\nruns_dir = "{tmp_path / "runs"}"\nplans_dirs = ["{SIMPLE.parent}"]\n')
    (tmp_path / "data.toml").write_text(f'[paths]\nsamples_dir = "{tmp_path / "samples"}"\n')
    return config.load(tmp_path)


@pytest.fixture
def client(cfg):
    return TestClient(create_app(cfg))


# ——— Новый дом ———

def test_form_choices_come_from_stub_config(client, cfg):
    got = client.get("/api/newhouse").json()
    spec = cfg.models.spec
    assert got["choices"]["styles"] == list(spec.style_words)
    assert got["choices"]["trims"] == list(spec.trim_words)
    assert got["shapes"] == list(ContourKind)
    options = client.get("/api/options").json()
    assert set(got["choices"]["walls"]) <= set(options["kind"])
    assert set(got["choices"]["styles"]) == set(options["style"])
    assert set(got["choices"]["trims"]) == set(options["trim"])
    assert set(got["shapes"]) == set(options["shape"])


def test_form_text_reads_back_without_loss(cfg):
    """Параметры → текст → параметры: всё, что названо, стаб прочитал так же."""
    spec = cfg.models.spec
    choices = spec_form.choices(spec)
    for kind in choices.walls:
        for roof in choices.roofs:
            form = spec_form.HouseForm(
                floors=2, wing_floors=1, style="classic", walls=kind, roof=roof,
                trims={Trim.SHUTTERS: False, Trim.CANOPY: True, Trim.SILL: True})
            read = spec_form.parse(spec_form.text(form, spec), spec)
            assert (read.floors, read.wing_floors, read.style) == (2, 1, "classic")
            # общий вид («кирпич») называет и свои частные виды: стаб выбирает среди них
            named = {kind, *(k for k, general in spec.material_like.items() if general == kind)}
            assert read.walls in named and read.roof == roof
            assert [read.trims[t] for t in (Trim.SHUTTERS, Trim.CANOPY, Trim.SILL)] == [
                False, True, True]


def _palette(form, spec) -> dict[str, str | None]:
    """Цвета ролей палитры, которые стаб построил по описанию из параметров."""
    house = stub.spec_model(spec_form.text(form, spec), spec)
    return {m.id: m.color for m in house.materials}


def test_named_color_reaches_the_palette(cfg):
    """Назван цвет — у стаба он среди цветов с этим словом; roof красит крышу, не стены."""
    spec = cfg.models.spec
    choices = spec_form.choices(spec)
    for kind, colors in choices.wall_colors.items():
        for color in colors:
            form = spec_form.HouseForm(walls=kind, wall_color=color.name, roof=RoofKind.GABLE,
                                       roof_color="black")
            by_id = _palette(form, spec)
            words = {c.hex for c in spec.colors.values() if color.name in c.words}
            assert by_id["main"] in words, (kind, color.name)
            assert by_id["roof"] in {c.hex for c in spec.colors.values() if "black" in c.words}


def test_wall_color_without_kind_does_not_paint_the_roof(cfg):
    """Цвет красит роль слова, что стоит за ним ближе `reach` слов: «белые стены» не должны
    красить крышу, названную сразу после — поэтому цвет стен идёт в конце описания."""
    spec = cfg.models.spec
    form = spec_form.HouseForm(wall_color="white", roof=RoofKind.GABLE)
    by_id = _palette(form, spec)
    assert by_id["main"] == spec.colors["white"].hex
    assert by_id["roof"] != spec.colors["white"].hex


def test_form_settles_after_two_readings(cfg):
    """Выбор вида стен внутри общего вида («кирпич») идёт от текста, поэтому первое чтение может
    уточнить вид; со второго параметры не меняются — форма и текст сходятся."""
    spec = cfg.models.spec
    for text in ("", "two-storey brick house with a gable roof, no shutters",
                 "одноэтажный дом с гаражом, красная крыша, деревянные стены"):
        second = spec_form.parse(spec_form.text(spec_form.parse(text, spec), spec), spec)
        third = spec_form.parse(spec_form.text(second, spec), spec)
        assert third == second, text


def test_text_and_spec_endpoints(client):
    text = client.post("/api/spec/text", json={"floors": 2, "roof": "hip",
                                              "trims": {"shutters": False}}).json()["text"]
    got = client.post("/api/spec", json={"text": text}).json()
    assert got["form"]["floors"] == 2 and got["form"]["roof"] == RoofKind.HIP
    assert got["form"]["trims"]["shutters"] is False
    assert set(got["colors"]) >= {"main", "trim", "roof"}


def test_unknown_form_field_is_refused(client):
    res = client.post("/api/spec/text", json={"floors": 2, "colour": "red"})
    assert res.status_code == 422 and res.json()["detail"]["code"] == "invalid_request"


@pytest.mark.parametrize("shape", list(ContourKind))
def test_random_plan_has_its_shape_and_is_a_plan(client, cfg, shape):
    """Случайный план — SVG GenPlan; тот же номер — тот же план; вид контура — выбранный."""
    from genfacade.datasets.synthetic import build, contour
    from genfacade.viewer.newhouse import random_plan

    first = client.get(f"/api/plans/random/{shape}/0.svg")
    assert first.status_code == 200 and "<rect" in first.text
    assert client.get(f"/api/plans/random/{shape}/0.svg").text == first.text
    assert client.get(f"/api/plans/random/{shape}/1.svg").text != first.text
    seed, _ = random_plan(shape, 1, cfg)
    assert contour.pick(seed, build.with_norms(cfg).synthetic) is shape


def test_random_plan_runs_through_the_module(client):
    svg = client.get(f"/api/plans/random/{ContourKind.RECT}/0.svg").text
    res = client.post("/api/runs", json={
        "plan_run": {"plan": "random-rectangle-1", "text": "", "mode": Mode.BLIND}, "svg": svg})
    assert res.status_code in (200, 400)  # годится стаб — лист; нет — отказ с причиной
    if res.status_code == 400:
        assert res.json()["detail"]["code"]


# ——— Данные ———

def test_data_empty_without_samples(client):
    assert client.get("/api/data").json()["sets"] == []


def test_data_counts_and_shares(client, sample, tmp_path, cfg):
    root = tmp_path / "samples"
    for name in ("a", "b", "c"):
        store.write(sample.model_copy(update={"id": name}), root)
    store.write_manifest(root, Source.SYNTHETIC)
    data = client.get("/api/data").json()
    [found] = data["sets"]
    assert (found["source"], found["samples"], found["walls"]) == (Source.SYNTHETIC, 3, 12)
    assert found["title"] == cfg.viewer.data_view.sets[Source.SYNTHETIC].title
    assert found["shares"]["of"] == 3
    assert set(found["shares"]["attrs"]) == set(DataAttr) == set(data["attrs"])
    for rows in found["shares"]["attrs"].values():
        assert sum(r["share"] for r in rows) == pytest.approx(1.0)
        assert all(r["label"] for r in rows)
    roof = found["shares"]["attrs"][DataAttr.ROOF][0]
    assert roof["label"] == cfg.viewer.labels.roof[sample.sheet.spec.roof.kind]
    assert len(found["examples"]) <= cfg.viewer.data_view.examples


# ——— Правила ———

def test_every_rule_number_is_the_config_number(client, cfg):
    shown = {r["id"]: r for r in client.get("/api/rules").json()}
    assert set(shown) == {i.id for i in cfg.viewer.rules.item}
    assert shown["corner"]["value"] == cfg.checks.corner_min_m
    assert shown["door_spread"]["value"] == cfg.checks.door_spread_m
    pier = next(g for g in cfg.guidelines.guideline if g.id == "pier_min")
    assert shown["pier"]["value"] == pier.params["min"]
    assert shown["pier"]["sources"] and shown["pier"]["sources"][0]["quote"]
    assert [i["caption"] for i in shown["pier"]["images"]] == [
        cfg.viewer.rules.captions[v] for v in RuleVariant]


def test_changed_config_number_changes_the_page(tmp_path):
    (tmp_path / "checks.toml").write_text("corner_min_m = 0.77\n")
    found = TestClient(create_app(config.load(tmp_path))).get("/api/rules").json()
    got = {r["id"]: r for r in found}
    assert got["corner"]["value"] == 0.77


def test_rule_pictures_show_good_and_bad(client, cfg):
    """Картинка «так» и «не так» — разные стены одного вида; каждый вид правила нарисован."""
    assert {i.draw for i in cfg.viewer.rules.item} == set(RuleDraw)
    for item in cfg.viewer.rules.item:
        good, bad = (client.get(f"/api/rules/{item.id}/{v}.svg") for v in RuleVariant)
        assert good.status_code == bad.status_code == 200, item.id
        assert good.text.startswith("<svg") and good.text != bad.text, item.id
    assert client.get("/api/rules/nope/good.svg").json()["detail"]["code"] == "no_rule"


def test_corner_picture_puts_window_at_number_times_factor(cfg):
    item = next(i for i in cfg.viewer.rules.item if i.draw is RuleDraw.CORNER)
    for factor in (item.good, item.bad):
        spec, elements = rules._DRAW[item.draw](cfg, rules.value(item, cfg) * factor)
        window = next(e for e in elements if e.id == "w1")
        assert window.x_m == pytest.approx(round(cfg.checks.corner_min_m * factor, 3))


# ——— страницы ———

@pytest.mark.parametrize("path", ["/", "/rules"])
def test_pages_use_shared_topbar_and_theme(client, path):
    html = client.get(path).text
    assert 'id="topbar"' in html and "/static/theme.css" in html
    assert not re.search(r"#[0-9a-fA-F]{6}\b", STATIC.joinpath("rules.css").read_text())


def test_nav_lists_rules_once():
    text = STATIC.joinpath("shell.js").read_text()
    assert text.count('page: "rules"') == 1
