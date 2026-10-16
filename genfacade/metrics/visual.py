"""Визуальное сходство (`evaluation: Пять групп метрик`, gf#143): FID и KID по растрам стен.

Стена растрируется маской классов, как разметка CMP, а не оформленным листом: цвета и подписи
листа даёт отрисовка, а не метод, и у эталона в разметке их нет. Признаки — Inception v3 из
torch-fidelity (веса эталонной TF-реализации FID), числа — его же формулами.

torch и torch-fidelity — в группе [visual] и импортируются только в `features` и `scores`:
остальные метрики считаются без них.
"""

from functools import cache
from importlib.util import find_spec

import numpy

from genfacade.config import Visual
from genfacade.schema import Device, ElementClass, FacadeSheet, HouseSpec, SideFacade

FEATURES = "2048"  # слой Inception, по которому считают FID и KID в оригинальных работах


def available() -> bool:
    return find_spec("torch_fidelity") is not None


def rgb(color: str) -> tuple[int, int, int]:
    """'#rrggbb' → (r, g, b)."""
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def mask(f: SideFacade, spec: HouseSpec, cfg: Visual) -> numpy.ndarray:
    """Маска стены H×W×3 uint8, верх картинки — верх стены: фон, стена цветом facade,
    элементы — цветом класса поверх в порядке листа (подоконник рисуется после окна)."""
    width_m, height_m = cfg.canvas_m
    shape = (round(height_m * cfg.px_per_m), round(width_m * cfg.px_per_m), 3)
    img = numpy.empty(shape, numpy.uint8)
    img[:] = rgb(cfg.background)
    # Шаг один на все стены, чтобы размеры окон сравнивались; не влезает — стена уменьшается.
    scale = cfg.px_per_m * min(1.0, width_m / f.side.length_m, height_m / spec.eaves_m)
    _fill(img, (0.0, 0.0, f.side.length_m, spec.eaves_m), scale,
          rgb(cfg.colors[ElementClass.FACADE]))
    for e in f.elements:
        _fill(img, (e.x_m, e.y_m, e.w_m, e.h_m), scale, rgb(cfg.colors[e.cls]))
    return img


def _fill(img: numpy.ndarray, box: tuple[float, float, float, float], scale: float,
          color: tuple[int, int, int]) -> None:
    """Прямоугольник (x, y низа, w, h) в метрах; y растра идёт сверху вниз."""
    x, y, w, h = box
    rows = img.shape[0]
    x0, x1 = round(x * scale), round((x + w) * scale)
    top, bottom = rows - round((y + h) * scale), rows - round(y * scale)
    img[max(top, 0):max(bottom, 0), max(x0, 0):max(x1, 0)] = color


def masks(sheets: list[FacadeSheet], cfg: Visual) -> list[numpy.ndarray]:
    return [mask(f, s.spec, cfg) for s in sheets for f in s.facades]


@cache
def _inception(device: Device):
    """Сеть грузится один раз; веса при первом вызове качаются в кэш torch."""
    from torch_fidelity.feature_extractor_inceptionv3 import FeatureExtractorInceptionV3

    from genfacade.train import sampling

    net = FeatureExtractorInceptionV3("inception-v3-compat", [FEATURES]).eval()
    return net.to(sampling.device(device))


def features(images: list[numpy.ndarray], cfg: Visual) -> numpy.ndarray:
    """Признаки Inception растров H×W×3 uint8: N×2048. Размер под сеть приводит сама сеть."""
    import torch

    net, out = _inception(cfg.device), []
    on = next(net.parameters()).device
    with torch.no_grad():
        for k in range(0, len(images), cfg.batch):
            x = numpy.stack(images[k:k + cfg.batch]).transpose(0, 3, 1, 2)
            out.append(net(torch.from_numpy(x).to(on))[0].cpu().numpy())
    return numpy.concatenate(out) if out else numpy.empty((0, int(FEATURES)))


def scores(ours: numpy.ndarray, ref: numpy.ndarray, cfg: Visual) -> dict[str, float | None]:
    """FID и KID (среднее по подвыборкам) признаков против эталона; меньше двух растров — None.
    У совпадающих выборок оба около нуля, KID — несмещённая оценка и бывает чуть меньше нуля."""
    import torch
    from torch_fidelity.metric_fid import fid_features_to_statistics, fid_statistics_to_metric
    from torch_fidelity.metric_kid import kid_features_to_metric

    if min(len(ours), len(ref)) < 2:
        return {"fid": None, "kid": None}
    a, b = torch.from_numpy(ours), torch.from_numpy(ref)
    fid = fid_statistics_to_metric(fid_features_to_statistics(a), fid_features_to_statistics(b),
                                   verbose=False)
    kid = kid_features_to_metric(a, b, kid_subsets=cfg.kid_subsets, verbose=False,
                                 kid_subset_size=min(cfg.kid_subset, len(ours), len(ref)))
    # + 0.0: округлённый шум вокруг нуля печатается 0.0, а не -0.0
    return {"fid": round(float(fid["frechet_inception_distance"]), 4) + 0.0,
            "kid": round(float(kid["kernel_inception_distance_mean"]), 6) + 0.0}
