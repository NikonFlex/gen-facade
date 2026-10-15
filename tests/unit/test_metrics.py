"""Метрики оценки (gf#16; `evaluation: Пять групп метрик`, `evaluation: Согласованность с
планом`, `evaluation: Соответствие описанию`, `evaluation: SVD-метрика — вспомогательная`,
`evaluation: Метрики одной командой`).

Каждая метрика проверяется с двух концов: эталон генератора проходит, подмена, которая бьёт в
её группу, — нет. Если метрика их не различает, она ничего не мерит.
"""

import json

import pytest

from genfacade.cli import main
from genfacade.datasets.synthetic import batch
from genfacade.metrics import calibrate, measures, table
from genfacade.schema import ElementClass, ForbiddenZone, Mode, Source
from genfacade.unfold import unfold

HOUSES = 12
VAL_HALF = "[build]\nval_share = 0.5\n"


@pytest.fixture(scope="module")
def calibrated(tmp_path_factory):
    """Дома синтетики (половина в val) и калибровка по ним: строки таблицы по режимам."""
    from genfacade import config

    root = tmp_path_factory.mktemp("calib")
    folder = root / "cfg"
    folder.mkdir()
    (folder / "data.toml").write_text(f'[paths]\nsamples_dir = "{root / "data"}"\n')
    (folder / "synthetic.toml").write_text(VAL_HALF)
    cfg = config.load(folder)
    batch.run(range(HOUSES), cfg)
    out = calibrate.run(Source.SYNTHETIC, cfg, root / "out")
    return {m: {k.rsplit("/", 1)[-1]: r for k, r in
                json.loads((out / m / table.METRICS).read_text())["rows"].items()} for m in Mode}


@pytest.mark.parametrize("mode", list(Mode))
def test_generator_passes_every_check(calibrated, mode):
    r = calibrated[mode]["generator"]
    assert (r["valid"], r["geometry"], r["plan"], r["description"]) == (1.0, 1.0, 1.0, 1.0)


@pytest.mark.parametrize(("column", "substitutes"), [
    ("geometry", ("random", "foreign", "constant")),
    ("plan", ("foreign", "constant", "empty")),
    ("description", ("empty",)),
    ("diversity", ("constant", "empty")),
])
def test_generator_beats_substitutes(calibrated, column, substitutes):
    rows = calibrated[Mode.WITH_OPENINGS]
    for name in substitutes:
        assert rows[name][column] < rows["generator"][column], name


def test_structure_is_closer_for_generator(calibrated):
    rows = calibrated[Mode.BLIND]
    for name in ("random", "constant", "empty"):
        assert rows[name]["structure"] > rows["generator"]["structure"], name


def test_svd_is_perfect_on_empty_facade(calibrated):
    """Сценарий «Пустой фасад»: SVD-метрика идеальна, а окон на стену — 0, это видно рядом."""
    r = calibrated[Mode.BLIND]["empty"]
    assert (r["svd"], r["windows_per_wall"]) == (0.0, 0.0)


def _folder(path, sheets):
    path.mkdir()
    for k, s in enumerate(sheets):
        (path / f"h{k}.json").write_text(s.model_dump_json())
    return path


def test_unparsed_answer_is_not_valid(cfg, house, tmp_path):
    folder = _folder(tmp_path / "f", [house])
    (folder / "broken.json").write_text(json.dumps({"error": "ждали <end>"}))
    items = table.load(folder, cfg)
    r = table.row(items, table.reference(items), cfg)
    assert (r["valid"], r["geometry"], r["plan"]) == (0.5, 0.5, 0.5)


def test_window_in_forbidden_zone_breaks_plan_agreement(cfg, house, tmp_path):
    """Сценарий «Фасад с окном в запретной зоне»: фасад не засчитан согласованным."""
    k, f = next((k, f) for k, f in enumerate(house.facades) if measures.windows(f))
    w = measures.windows(f)[0]
    side = f.side.model_copy(update={"forbidden": [ForbiddenZone(x0_m=w.x_m, x1_m=w.x_m + 0.1)]})
    facades = list(house.facades)
    facades[k] = f.model_copy(update={"side": side})
    bad = house.model_copy(update={"facades": facades})
    items = table.load(_folder(tmp_path / "f", [house, bad]), cfg)
    r = table.row(items, table.reference(items), cfg)
    assert (r["geometry"], r["plan"]) == (1.0, 0.5)


def _two_storey(sheet, upper: bool):
    """Тот же дом в два этажа; upper — окно второго этажа над первым окном."""
    spec = sheet.spec.model_copy(update={"floors": 2, "floor_heights_m": [2.75, 2.75],
                                          "eaves_m": sheet.spec.plinth_m + 5.5})
    sheet = unfold(sheet.model_copy(update={"spec": spec}))
    if not upper:
        return sheet
    k, f = next((k, f) for k, f in enumerate(sheet.facades) if measures.windows(f))
    w = measures.windows(f)[0]
    up = w.model_copy(update={"id": "upper", "floor": 2, "y_m": w.y_m + 2.75, "fixed": []})
    facades = list(sheet.facades)
    facades[k] = f.model_copy(update={"elements": [*f.elements, up]})
    return sheet.model_copy(update={"facades": facades})


def test_two_storey_text_and_one_storey_facade(house):
    """Сценарий «Два этажа в тексте»: окна только на первом этаже — этажность не выполнена."""
    assert measures.floors_kept(house)
    assert not measures.floors_kept(_two_storey(house, upper=False))
    assert measures.floors_kept(_two_storey(house, upper=True))


def test_same_folder_as_reference_is_at_distance_zero(cfg, house, tmp_path):
    items = table.load(_folder(tmp_path / "f", [house, _two_storey(house, upper=True)]), cfg)
    r = table.row(items, table.reference(items), cfg)
    assert r["structure"] == 0.0


def test_wasserstein_of_shift_is_the_shift():
    assert measures.wasserstein([0.0, 1.0, 2.0], [0.5, 1.5, 2.5], 100) == pytest.approx(0.5)


def test_svd_sees_misaligned_windows(cfg, house):
    k, f = next((k, f) for k, f in enumerate(house.facades) if measures.windows(f))
    w = measures.windows(f)[0]
    low = w.model_copy(update={"id": "low", "x_m": w.x_m + w.w_m + 0.5, "y_m": w.y_m - 0.4})
    aligned = measures.svd_score(f, house.spec, cfg.metrics.svd)
    broken = f.model_copy(update={"elements": [*f.elements, low]})
    assert measures.svd_score(broken, house.spec, cfg.metrics.svd) > aligned


def test_one_command_prints_every_column(house, tmp_path, capsys):
    folder = _folder(tmp_path / "f", [house])
    main(["metrics", str(folder), "-r", str(folder), "-o", str(tmp_path / "out")])
    header = capsys.readouterr().out.splitlines()[0]
    assert all(c in header for c in table.COLUMNS)
    assert (tmp_path / "out" / table.METRICS).exists()


def test_floor_is_taken_from_height_not_from_field(house):
    f = next(f for f in house.facades if measures.windows(f))
    w = measures.windows(f)[0].model_copy(update={"floor": 2})
    assert w.cls is ElementClass.WINDOW and measures.floor_of(w, house.spec) == 1
