"""Растр от генератора (gf#17): промпт из параметров дома, размер по пропорции стены, маска
ControlNet и мост «рамка на картинке → элемент в метрах». Модель и детектор — заглушки."""

import numpy
import pytest
from PIL import Image

from genfacade import generator
from genfacade.metrics import visual
from genfacade.schema import ElementClass

TOL_M = 0.12  # рамка с картинки точна до пикселя: при 1024 px на стену — сантиметры


@pytest.fixture
def wall(house):
    """Стена простого дома с окном и её параметры."""
    f = next(f for f in house.facades if any(e.cls is ElementClass.WINDOW for e in f.elements))
    return f, house.spec


def test_size_follows_wall_proportion(wall, cfg):
    f, spec = wall
    run = cfg.baselines.generator.size
    for long_side in (1024, 512):
        width, height = generator.size(f, spec, long_side, cfg)
        assert max(width, height) == pytest.approx(long_side, abs=run.step_px)
        assert width % run.step_px == 0 and height % run.step_px == 0
        assert (width > height) == (f.side.length_m > spec.eaves_m)


def test_size_of_a_long_low_wall_keeps_the_minimum_side(wall, cfg):
    f, spec = wall
    long = f.model_copy(update={"side": f.side.model_copy(update={"length_m": 40.0})})
    _, height = generator.size(long, spec, 1024, cfg)
    assert height == cfg.baselines.generator.size.min_side_px


def test_prompt_is_the_house_in_words(house, cfg):
    text = generator.prompt(house.spec, cfg)
    main = next(m for m in house.spec.materials if m.id == "main")
    assert f"{house.spec.floors}-storey" in text
    assert house.spec.roof.kind.value in text
    assert main.kind.replace("_", " ") in text
    assert cfg.baselines.generator.prompt.drawing in text


def test_color_is_named_by_the_nearest_word(cfg):
    assert generator.color_name("#fafafa", cfg) == "white"
    assert generator.color_name("#8a4838", cfg) == "red brick"


def _paint(wall, cfg, width, height):
    """Картинка стены: серый фон и окно цветом, как его нарисовал бы генератор."""
    f, spec = wall
    window = next(e for e in f.elements if e.cls is ElementClass.WINDOW)
    image = numpy.full((height, width, 3), 200, numpy.uint8)
    sx, sy = width / f.side.length_m, height / spec.eaves_m
    image[round(height - (window.y_m + window.h_m) * sy):round(height - window.y_m * sy),
          round(window.x_m * sx):round((window.x_m + window.w_m) * sx)] = (0, 68, 255)
    return window, Image.fromarray(image)


def _by_color():
    """Детектор-заглушка: рамка области цвета (0, 68, 255) — окно."""
    def detect(picture):
        rows, cols = numpy.nonzero((numpy.asarray(picture) == (0, 68, 255)).all(axis=2))
        box = (float(cols.min()), float(rows.min()), float(cols.max() + 1), float(rows.max() + 1))
        return [(box, ElementClass.WINDOW)]
    return detect


def test_bridge_puts_the_window_where_it_was_drawn(wall, cfg):
    f, spec = wall
    width, height = generator.size(f, spec, 1024, cfg)
    window, image = _paint(wall, cfg, width, height)
    got = generator.bridge(image, f, spec, _by_color(), cfg)
    assert len(got) == 1
    assert got[0].cls is ElementClass.WINDOW
    for field in ("x_m", "y_m", "w_m", "h_m"):
        assert getattr(got[0], field) == pytest.approx(getattr(window, field), abs=TOL_M)
    assert got[0].floor == window.floor


def test_bridge_corrects_the_stretch_of_a_snapped_picture(wall, cfg):
    """Высота картинки округлена до шага — масштаб по осям разный; рамка в метрах — всё равно."""
    f, spec = wall
    window = next(e for e in f.elements if e.cls is ElementClass.WINDOW)
    far = window.model_copy(update={"x_m": 6.0})
    long = f.model_copy(update={"elements": [far], "side": f.side.model_copy(update={
        "length_m": 9.0})})
    width, height = generator.size(long, spec, 1024, cfg)
    assert abs(width / 9.0 - height / spec.eaves_m) > 3  # без этого тест ничего не проверяет
    _, image = _paint((long, spec), cfg, width, height)
    got = generator.bridge(image, long, spec, _by_color(), cfg)
    assert got[0].x_m == pytest.approx(6.0, abs=TOL_M)
    assert got[0].w_m == pytest.approx(far.w_m, abs=TOL_M)
    assert got[0].h_m == pytest.approx(far.h_m, abs=TOL_M)


def test_bridge_drops_a_box_that_is_not_a_window(wall, cfg):
    f, spec = wall
    width, height = generator.size(f, spec, 1024, cfg)
    image = Image.new("RGB", (width, height))
    whole_wall = [((0.0, 0.0, float(width), float(height)), ElementClass.WINDOW),
                  ((5.0, 5.0, 6.0, 6.0), ElementClass.WINDOW)]
    assert generator.elements(whole_wall, image, f, spec, cfg) == []


def test_control_mask_has_the_plan_openings_in_their_colors(wall, cfg):
    f, spec = wall
    width, height = 512, 256
    mask = generator.control(f, spec, width, height, cfg)
    run = cfg.baselines.generator.cnet
    assert mask.shape == (height, width, 3)
    window = next(e for e in f.elements if e.cls is ElementClass.WINDOW)
    x = round((window.x_m + window.w_m / 2) / f.side.length_m * width)
    y = round(height - (window.y_m + window.h_m / 2) / spec.eaves_m * height)
    assert tuple(mask[y, x]) == visual.rgb(run.window)
    assert tuple(mask[1, 1]) == visual.rgb(run.facade)
