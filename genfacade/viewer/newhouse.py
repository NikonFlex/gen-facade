"""Страница «Новый дом» (gf#356): параметры дома → описание → прогон.

Модуль принимает план и текст, поэтому форма параметров — надстройка над текстом: сервер собирает
описание словами конфига и читает его обратно тем же стабом шага 1 (`models/spec_form.py`).
Случайный план — тот же генератор синтетики, что собирает корпус (`datasets/synthetic`), вид
контура на выбор: seed ищется среди тех, для которых `contour.pick` даёт этот вид.
"""

from fastapi import FastAPI, Response
from pydantic import BaseModel

from genfacade.config import Config
from genfacade.datasets import genplan_writer
from genfacade.datasets.synthetic import build, contour
from genfacade.models import spec_form, stub
from genfacade.schema import ContourKind

MAX_VARIANT = 10_000  # дальше номера варианта искать seed незачем: страница столько не просит


class DescriptionIn(BaseModel):
    text: str


def random_plan(kind: ContourKind, variant: int, cfg: Config) -> tuple[int, str]:
    """Вариант номер `variant` (с нуля) плана данного вида: seed и текст SVG в формате GenPlan."""
    syn = build.with_norms(cfg).synthetic
    seeds = (s for s in range(MAX_VARIANT * 20) if contour.pick(s, syn) is kind)
    seed = next(s for i, s in enumerate(seeds) if i == variant)
    return seed, genplan_writer.svg(contour.draft(seed, syn), syn.canvas)


def api(app: FastAPI, cfg: Config) -> None:
    spec = cfg.models.spec

    @app.get("/api/newhouse")
    def options() -> dict:
        """Что можно выбрать в форме и виды контура случайного плана."""
        return {"choices": spec_form.choices(spec).model_dump(mode="json"),
                "shapes": [k.value for k in ContourKind]}

    @app.post("/api/spec/text")
    def to_text(form: spec_form.HouseForm) -> dict:
        return {"text": spec_form.text(form, spec)}

    @app.post("/api/spec")
    def to_form(body: DescriptionIn) -> dict:
        """Стаб шага 1 читает описание, ответ — в поля формы и цвета ролей палитры."""
        house = stub.spec_model(body.text, spec)
        colors = {m.id: m.color or cfg.library.kinds.get(m.kind) for m in house.materials}
        return {"form": spec_form.form_of(house, spec).model_dump(mode="json"), "colors": colors}

    @app.get("/api/plans/random/{shape}/{variant}.svg")
    def random_svg(shape: ContourKind, variant: int) -> Response:
        return Response(random_plan(shape, max(variant, 0), cfg)[1], media_type="image/svg+xml")
