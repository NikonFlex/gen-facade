"""Пример датасета в смотрелке: тот же вид, что у прогона, — план и лист (dev-plan.md).

Рисует тот же render/, что и конвейер; папка просмотра лежит рядом с прогонами.
"""

from pathlib import Path

from genfacade import pipeline
from genfacade.config import Config
from genfacade.render.plan_svg import plan_svg
from genfacade.schema import Sample


def run_id(sample: Sample) -> str:
    return f"sample-{sample.source}-{sample.id}"


def render(sample: Sample, cfg: Config) -> Path:
    """План (если он есть) и лист примера → папка просмотра в runs_dir."""
    out = cfg.viewer.paths.runs_dir / run_id(sample)
    out.mkdir(parents=True, exist_ok=True)
    shown = {pipeline.SHEET}
    if sample.plan is not None:
        (out / pipeline.PLAN_SVG).write_text(plan_svg(sample.plan, cfg))
        shown.add(pipeline.PLAN_SVG)
    return pipeline.finish(sample.sheet, out, cfg, {
        "source": f"{sample.source}/{sample.id}",
        "steps": [s._asdict() for s in pipeline.STEPS if s.file in shown],
        "sample": sample.model_dump(mode="json", include={"id", "source", "split", "texts"}),
    })
