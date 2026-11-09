"""Базовый подход «растр + готовый векторизатор» (gf#17): стена → растр плоскими цветами классов →
векторизатор → элементы. Сторонний векторизатор в тестах — заглушка: связные области цвета с
рамкой, как отдал бы любой трассировщик чистого растра."""

import json
from collections import deque

import numpy
import pytest

from genfacade import vectorizer
from genfacade.metrics import damage, realtest, visual
from genfacade.schema import Element, ElementClass, FacadeSheet, Mode
from genfacade.vectorizer import Backend, Extracted, Shape, Traced

STEP = 4  # заглушка смотрит на каждый четвёртый пиксель: быстро, рамка точна до STEP пикселей


def regions(image: numpy.ndarray) -> list[Shape]:
    """Связные области одного цвета (4 соседа) → цвет и осевая рамка."""
    small = image[::STEP, ::STEP]
    seen = numpy.zeros(small.shape[:2], bool)
    out = []
    for start in zip(*numpy.nonzero(~seen), strict=True):
        if seen[start]:
            continue
        color, queue, cells = tuple(int(c) for c in small[start]), deque([start]), []
        seen[start] = True
        while queue:
            r, c = queue.popleft()
            cells.append((r, c))
            for n in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                inside = 0 <= n[0] < small.shape[0] and 0 <= n[1] < small.shape[1]
                if inside and not seen[n] and tuple(small[n]) == color:
                    seen[n] = True
                    queue.append(n)
        rows, cols = zip(*cells, strict=True)
        box = (min(cols) * STEP, min(rows) * STEP, (max(cols) + 1) * STEP, (max(rows) + 1) * STEP)
        out.append(Shape(color=color, box=box, segments=4))
    return out


@pytest.fixture
def traced_by_stub(monkeypatch):
    """`trace` вместо стороннего процесса: ответ на каждый растр — области заглушки."""
    def stub(backend, cfg, out):
        (out / vectorizer.TRACED).mkdir(exist_ok=True)
        for path in (out / vectorizer.RASTERS).glob("*.npy"):
            answer = Traced(seconds=1.0, shapes=regions(numpy.load(path)))
            (out / vectorizer.TRACED / f"{path.stem}.json").write_text(answer.model_dump_json())

    monkeypatch.setattr(vectorizer, "trace", stub)


def _windows(sheet) -> list[Element]:
    return [e for f in sheet.facades for e in f.elements if e.cls is ElementClass.WINDOW]


def test_palette_class_is_found_by_its_own_color(cfg):
    for cls, color in cfg.baselines.vectorizer.colors.items():
        assert vectorizer.nearest(visual.rgb(color), cfg) is cls


def test_clean_raster_gives_back_every_window_in_place(real, cfg, traced_by_stub, tmp_path):
    """Растр чистый, векторизатор не врёт: окна, двери и их число — как у эталона."""
    vectorizer.run(Backend.VTRACER, cfg, tmp_path, 0)
    got = Extracted.model_validate_json((tmp_path / "h0.json").read_text())
    ref = real["h0"]
    tolerance = STEP * 2 / vectorizer.scale(ref.facades[0], ref.spec, cfg)
    for f, found in zip(ref.facades, got.walls, strict=True):
        theirs = [e for e in found if e.cls is ElementClass.WINDOW]
        mine = [e for e in f.elements if e.cls is ElementClass.WINDOW]
        assert len(theirs) == len(mine)
        for e in mine:
            assert any(abs(e.x_m - t.x_m) < tolerance and abs(e.y_m - t.y_m) < tolerance
                       and abs(e.w_m - t.w_m) < tolerance for t in theirs), e.id
    report = json.loads((tmp_path / "damage.json").read_text())
    assert report["window.matched"] == report["window.ref"] == len(real) * len(_windows(ref))


def test_row_sheet_keeps_house_and_swaps_walls(real, cfg, traced_by_stub, tmp_path):
    vectorizer.run(Backend.VTRACER, cfg, tmp_path / "v", 0)
    row = vectorizer.write_row(real, tmp_path / "v", tmp_path / "row")
    made = FacadeSheet.model_validate_json((row / "h0.json").read_text())
    assert made.spec == real["h0"].spec
    assert [f.side for f in made.facades] == [f.side for f in real["h0"].facades]
    assert all(len(f.zones) == 1 for f in made.facades)


def test_limit_takes_the_first_houses_of_the_order(real, cfg, tmp_path):
    assert sorted(vectorizer.order(list(real), cfg)) == list(real)
    walls = vectorizer.write_rasters(real, cfg, tmp_path, 1)
    assert walls == len(real["h0"].facades)


def _box(cls, x, w=1.0, y=1.0, h=1.5) -> Element:
    return Element(id="e", cls=cls, x_m=x, y_m=y, w_m=w, h_m=h, floor=1)


@pytest.mark.parametrize(("found", "expected"), [
    ([_box(ElementClass.WINDOW, 0.02)], "matched"),
    ([_box(ElementClass.DOOR, 0.0)], "wrong_class"),
    ([_box(ElementClass.WINDOW, 0.0, w=0.45), _box(ElementClass.WINDOW, 0.55, w=0.45)], "split"),
    ([_box(ElementClass.WINDOW, 0.0, w=0.3)], "partial"),
    ([_box(ElementClass.WINDOW, -0.5, w=3.0)], "merged"),
    ([_box(ElementClass.WINDOW, 5.0)], "lost"),
])
def test_damage_outcome_of_a_window(found, expected, cfg):
    ref = _box(ElementClass.WINDOW, 0.0)
    assert damage.outcome(ref, found, cfg.baselines.vectorizer.match_iou) == expected


def test_vectorizer_row_is_counted_on_the_houses_it_finished(real, cfg, traced_by_stub, tmp_path):
    """Не все дома готовы: в строке — готовые, остальные строки — и против тех же домов."""
    done = tmp_path / "evo"
    vectorizer.run(Backend.VTRACER, cfg, done, 0)
    for gone in ("h2.json", "h3.json"):
        (done / gone).unlink()
    out = tmp_path / "table"
    realtest.run(cfg, out, 0, realtest.Rows({}, {}, {"evo": done}))
    for mode in Mode:
        rows = {k.rsplit("/", 1)[-1]: r for k, r in json.loads(
            (out / mode / "rows" / "metrics.json").read_text())["rows"].items()}
        assert rows["vectorizer-evo"]["count"] == 2
        same = json.loads((out / mode / "slices" / "vectorizer-evo-houses" / "metrics.json")
                          .read_text())["rows"]
        assert {r["count"] for r in same.values()} == {2}
        assert {k.rsplit("/", 1)[-1] for k in same} == {"vectorizer-evo", "genplan"}


def test_texture_dims_wall_lines_and_leaves_elements(real, cfg):
    """Полоски обшивки — только на стене, окна и двери остаются цветом класса."""
    f, spec = real["h0"].facades[0], real["h0"].spec
    dirty = cfg.model_copy(update={"baselines": cfg.baselines.model_copy(update={
        "vectorizer": cfg.baselines.vectorizer.model_copy(update={
            "texture": cfg.baselines.vectorizer.texture.model_copy(update={"siding_px": 6})})})})
    flat, rough = vectorizer.raster(f, spec, cfg), vectorizer.raster(f, spec, dirty)
    changed = (flat != rough).any(axis=2)
    assert changed.any()
    assert not changed.any(axis=1)[1::6].any()  # между линиями ничего не тронуто
    window = visual.rgb(cfg.baselines.vectorizer.colors[ElementClass.WINDOW])
    assert (flat[changed] != window).any(axis=1).all()
    assert (rough == window).all(axis=2).sum() == (flat == window).all(axis=2).sum()
