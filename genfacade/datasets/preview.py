"""Пример датасета в смотрелке: тот же вид, что у прогона, — план, токены и лист (dev-plan.md).

Рисует тот же render/, что и конвейер; папка просмотра лежит рядом с прогонами.
"""

import json
from pathlib import Path

from genfacade import pipeline
from genfacade.config import Config
from genfacade.render.plan_svg import plan_svg
from genfacade.schema import Mode, Sample
from genfacade.train import tokens

TOKENS = "tokens.json"
# Токены — то, что читает и пишет модель шага 4 схемы: в просмотре они на его месте.
TOKENS_STEP = pipeline.Step(4, "Токены", TOKENS)


def run_id(sample: Sample) -> str:
    return f"sample-{sample.source}-{sample.id}"


def render(sample: Sample, cfg: Config) -> Path:
    """План (если он есть), токены и лист примера → папка просмотра в runs_dir."""
    out = cfg.viewer.paths.runs_dir / run_id(sample)
    out.mkdir(parents=True, exist_ok=True)
    steps = [s for s in pipeline.STEPS if s.file == pipeline.SHEET]
    if sample.plan is not None:
        (out / pipeline.PLAN_SVG).write_text(plan_svg(sample.plan, cfg))
        steps += [s for s in pipeline.STEPS if s.file == pipeline.PLAN_SVG]
    written = _tokens(sample, cfg)
    if written is not None:
        (out / TOKENS).write_text(json.dumps(written, ensure_ascii=False, indent=2))
        steps.append(TOKENS_STEP)
    return pipeline.finish(sample.sheet, out, cfg, {
        "source": f"{sample.source}/{sample.id}",
        "steps": [s._asdict() for s in sorted(steps)],
        "tokens": TOKENS if written is not None else None,
        "sample": sample.model_dump(mode="json", include={"id", "source", "split", "texts"}),
    })


def _tokens(sample: Sample, cfg: Config) -> dict | None:
    """Режим → части последовательности (название, строки, число токенов); дом, который
    токенами не записывается (стиль или материал не из словаря), — без этого шага."""
    parts = (("Условие — дано модели", tokens.condition),
             ("Ответ — пишет модель", tokens.answer))
    try:
        return {mode: [{"title": title, "count": len(seq), "lines": tokens.lines(seq)}
                       for title, write in parts
                       for seq in [write(sample.sheet, mode, cfg)]]
                for mode in Mode}
    except tokens.TokenError:
        return None
