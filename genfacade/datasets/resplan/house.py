"""Дом ResPlan после перевода: план со сторонами и проёмами и откуда он."""

from pydantic import BaseModel

from genfacade.schema import Plan, Split


class House(BaseModel):
    """План частного дома ResPlan после препроцессора шага 2, в метрах ResPlan.

    plan.source — genplan: план прочитан из SVG в формате GenPlan, источник данных — этот файл.
    """

    id: str
    resplan_id: int
    split: Split
    layers: list[str]   # какие из слоёв дома (house_layers) у плана есть
    area_m2: float      # площадь из листинга — по ней масштаб
    plan: Plan
    # Сверка с исходником сошлась: каждое окно и дверь ResPlan у контура нашлись на своей стороне
    # с тем же видом, лишних проёмов на сторонах нет (check.py).
    matched: bool = False


def house_id(resplan_id: int) -> str:
    return f"resplan-{resplan_id}"
