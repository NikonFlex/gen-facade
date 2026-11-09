#!/usr/bin/env python3
"""Базовый подход «растр от генератора + готовый векторизатор» на реальном тесте (gf#17).

Каждой стене домов `data/samples/manual` генератор рисует картинку, vtracer векторизует её, OWLv2
ищет окна и двери, рамки в метрах → `<out>/<режим>/<дом>.json` (`Extracted`), и дальше
`genfacade realtest --vectorized sdxl=<out>/sdxl --vectorized cnet=<out>/cnet`.

  python tools/genbase.py sdxl cnet -o outputs/genbase --limit 3

  sdxl — глухой режим: SDXL по тексту из параметров дома;
  cnet — окна из плана: SD 1.5 + ControlNet по маске окон и дверей плана.

Нужны GPU, diffusers, transformers, vtracer, cairosvg (job `genbase` в gpu.yml ставит их).
Настройки — `[generator]` в config/baselines.toml. Картинки: `<out>/<режим>/images/<дом>__<стена>`
`.png` (генератор), `.svg` и `.svg.png` (vtracer), `.boxes.png` (найденные рамки);
`<out>/summary.json` — секунды на картинку.
"""
import argparse
import json
import sys
import tempfile
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from genfacade import generator, vectorizer  # noqa: E402
from genfacade.config import Config, load  # noqa: E402
from genfacade.schema import Mode  # noqa: E402
from genfacade.train.tokens import given_sides  # noqa: E402
from tools import owl_boxes  # noqa: E402


class Kind(StrEnum):
    SDXL = "sdxl"   # глухой режим: по тексту
    CNET = "cnet"   # окна из плана: по маске


def drawer(pipe, run, extra: Callable[[object], dict]):
    """Конвейер diffusers → `draw(текст, анти-текст, размер, маска, seed)` → картинка; `extra` — то,
    что есть только у этой модели (маска и вес ControlNet)."""
    import torch  # noqa: PLC0415 — тяжёлый импорт нужен только запуску

    pipe.to("cuda")

    def draw(text: str, negative: str, size: tuple[int, int], control, seed: int) -> Image.Image:
        gen = torch.Generator("cuda").manual_seed(seed)
        return pipe(prompt=text, negative_prompt=negative, width=size[0], height=size[1],
                    num_inference_steps=run.steps, guidance_scale=run.guidance, generator=gen,
                    **extra(control)).images[0]
    return draw


def sdxl_pipeline(cfg: Config):
    import torch  # noqa: PLC0415
    from diffusers import StableDiffusionXLPipeline  # noqa: PLC0415

    run = cfg.baselines.generator.sdxl
    pipe = StableDiffusionXLPipeline.from_pretrained(run.model, torch_dtype=torch.float16,
                                                     variant="fp16", use_safetensors=True)
    return drawer(pipe, run, lambda control: {})


def cnet_pipeline(cfg: Config):
    import torch  # noqa: PLC0415
    from diffusers import StableDiffusionControlNetPipeline  # noqa: PLC0415

    run = cfg.baselines.generator.cnet
    # репозиторий хранит конвейер в подпапке, а from_pretrained ищет model_index.json в корне:
    # качаем только её и грузим из локальной папки
    from huggingface_hub import snapshot_download  # noqa: PLC0415

    root = snapshot_download(run.model, allow_patterns=[f"{run.subfolder}/*"])
    folder = Path(root) / run.subfolder
    pipe = StableDiffusionControlNetPipeline.from_pretrained(
        folder, torch_dtype=torch.float16, safety_checker=None)
    return drawer(pipe, run, lambda control: {
        "image": Image.fromarray(control), "controlnet_conditioning_scale": run.conditioning_scale})


def trace(image: Image.Image, cfg: Config, target: Path) -> Image.Image:
    """Картинка → SVG vtracer (`target.svg`) → отрисовка того же размера."""
    import cairosvg  # noqa: PLC0415
    import vtracer  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as work:
        png = Path(work) / "wall.png"
        image.save(png)
        vtracer.convert_image_to_svg_py(str(png), str(target.with_suffix(".svg")),
                                        **cfg.baselines.vectorizer.vtracer.model_dump())
    svg, rendered = target.with_suffix(".svg"), target.with_suffix(".svg.png")
    cairosvg.svg2png(url=str(svg), write_to=str(rendered), output_width=image.width,
                     output_height=image.height, background_color="white")
    return Image.open(rendered).convert("RGB")


def detector(owl) -> generator.Detect:
    """OWLv2 `tools/owl_boxes` → рамки и классы; NMS — его же, отсев по размеру — наш."""
    def detect(image: Image.Image) -> list[generator.Found]:
        return [(tuple(b.box), b.cls) for b in owl_boxes.suppress(owl(image))]
    return detect


def mark(image: Image.Image, found: list[generator.Found]) -> Image.Image:
    """Найденные рамки поверх картинки: окна синим, двери коричневым."""
    out = image.copy()
    draw = ImageDraw.Draw(out)
    for box, cls in found:
        draw.rectangle(box, outline="#0044ff" if cls.value == "window" else "#8b4513", width=3)
    return out


def run(modes: list[Kind], cfg: Config, out: Path, limit: int) -> dict:
    real = vectorizer.houses(cfg)
    names = vectorizer.order(list(real), cfg)
    owl = detector(owl_boxes.owl_detector())
    run_cfg = cfg.baselines.generator
    summary: dict = {"modes": {}}
    for mode in modes:
        pipe = (sdxl_pipeline if mode is Kind.SDXL else cnet_pipeline)(cfg)
        settings = run_cfg.sdxl if mode is Kind.SDXL else run_cfg.cnet
        folder = out / mode.value
        (folder / "images").mkdir(parents=True, exist_ok=True)
        seconds, walls, houses = [], 0, {}
        for name in names:
            sheet = real[name] if mode is Kind.SDXL else given_sides(real[name], Mode.WITH_OPENINGS)
            answer, spent = [], 0.0
            for k, f in enumerate(sheet.facades):
                if limit and walls >= limit:
                    break
                start = time.perf_counter()
                width, height = generator.size(f, sheet.spec, settings.long_side_px, cfg)
                control = generator.control(f, sheet.spec, width, height, cfg) \
                    if mode is Kind.CNET else None
                text = generator.prompt(sheet.spec, cfg)
                image = pipe(text, run_cfg.prompt.negative, (width, height), control, run_cfg.seed)
                stem = folder / "images" / f"{name}__{k}"
                image.save(stem.with_suffix(".png"))
                seen = trace(image, cfg, stem) if run_cfg.detect.through_vtracer else image
                found = owl(seen)
                answer.append(generator.elements(found, seen, f, sheet.spec, cfg))
                mark(seen, found).save(stem.with_suffix(".boxes.png"))
                if control is not None:
                    Image.fromarray(control).save(stem.with_suffix(".mask.png"))
                took = time.perf_counter() - start
                seconds.append(round(took, 2))
                spent += took
                walls += 1
                print(mode.value, name, k, text, f"{took:.1f} c", flush=True)
            if len(answer) == len(sheet.facades):
                extracted = vectorizer.Extracted(seconds=round(spent, 1), walls=answer)
                (folder / f"{name}.json").write_text(extracted.model_dump_json())
                houses[name] = round(spent, 1)
            if limit and walls >= limit:
                break
        summary["modes"][mode.value] = {"walls": walls, "sec_per_wall": seconds,
                                        "houses_done": houses}
        del pipe
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("modes", nargs="+", type=Kind)
    parser.add_argument("-o", "--out", type=Path, default=Path("outputs/genbase"))
    parser.add_argument("-c", "--config", type=Path, action="append", default=[],
                        help="папка настроек поверх умолчаний (как `genfacade -c`)")
    parser.add_argument("--limit", type=int, default=0, help="сколько стен всего; 0 — все")
    args = parser.parse_args()
    run(args.modes, load(*args.config), args.out, args.limit)


if __name__ == "__main__":
    main()
