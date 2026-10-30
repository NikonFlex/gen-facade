"""Частные дома ResPlan → планы со сторонами и проёмами в метрах (`data: Стены с проёмами из
ResPlan`, gf#215). Пока не примеры обучения: эталона фасада у них нет, к обучению их подключает
gf#217.

    <out_dir>/<id>.json        House: план после препроцессора шага 2 и откуда он
    <out_dir>/svg/<id>.svg     тот же план в формате GenPlan — его можно открыть в смотрелке
    <out_dir>/_manifest.json   опись: отбор, дубли, отказы с причинами, датчик, сверка

Частный дом — план, у которого есть слой сада, парковки, бассейна или лестницы: поля «тип жилья»
в выпуске нет (ключи пикла, 30.10.2026). Дом — один план: этажи одного дома ResPlan не связывает.
"""

import json
import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy

from genfacade.config import Config
from genfacade.datasets.resplan import check, convert, dedup, load, preview
from genfacade.datasets.resplan.house import House, house_id
from genfacade.pipeline import git_sha
from genfacade.plan.genplan_svg import PlanError
from genfacade.plan.preprocess import preprocess
from genfacade.schema import ForbiddenZone, Mode, Plan, Rect, Side, Split

MANIFEST = "_manifest.json"
SVG_DIR = "svg"


def run(cfg: Config, preview_dir: Path | None, preview_count: int) -> Path:
    """Отобрать дома, убрать дубли, перевести каждый в план; вернуть путь к описи."""
    rules = cfg.data.resplan
    (rules.paths.out_dir / SVG_DIR).mkdir(parents=True, exist_ok=True)
    plans = load.plans(rules.paths.pickle)
    parts = load.splits(rules.paths.splits)
    houses = [p for p in plans if p["id"] in parts and _layers(p, rules.house_layers)]
    groups = dedup.clusters(houses, rules)
    kept = sorted((houses[min(g, key=lambda i: houses[i]["id"])] for g in groups),
                  key=lambda p: p["id"])
    outcome = _convert_all(kept, parts, cfg)
    if preview_dir is not None:
        rng = random.Random(0)  # noqa: S311 — тот же выбор при повторе, не криптография
        chosen = rng.sample(outcome.done, min(preview_count, len(outcome.done)))
        preview.write(chosen, {p["id"]: p for p in kept}, preview_dir, cfg)
    selection = {"plans": len(plans), "houses": len(houses),
                 "house_layers": dict(Counter(k for p in houses
                                              for k in _layers(p, rules.house_layers))),
                 "duplicates_dropped": len(houses) - len(groups), "unique_houses": len(groups)}
    return _write_manifest(rules.paths.out_dir, selection | outcome.summary(), cfg)


@dataclass
class Outcome:
    """Что вышло из перевода домов: готовые, отказы по причинам, сверка с исходником."""

    done: list[House] = field(default_factory=list)
    refused: Counter = field(default_factory=Counter)
    checks: list[check.Match] = field(default_factory=list)

    def summary(self) -> dict:
        per_house = [sum(len(s.openings) for s in h.plan.sides) for h in self.done]
        tried = len(self.done) + sum(self.refused.values())
        sides = [s for h in self.done for s in h.plan.sides]
        return {
            "converted": len(self.done),
            "matched": sum(h.matched for h in self.done),
            "refused": dict(self.refused),
            "closed_outline_share": round(len(self.done) / max(tried, 1), 4),
            "splits": dict(Counter(h.split for h in self.done)),
            "sides": len(sides),
            "sides_with_openings": sum(bool(s.openings) for s in sides),
            "openings": dict(Counter(o.kind for s in sides for o in s.openings)),
            "openings_per_house": {"mean": round(float(numpy.mean(per_house)), 2),
                                   "median": float(numpy.median(per_house))} if per_house else {},
            "check": check.total(self.checks),
        }


def _convert_all(kept: list[dict], parts: dict[int, Split], cfg: Config) -> Outcome:
    outcome = Outcome()
    for plan in kept:
        try:
            house, drawing = convert_house(plan, parts[plan["id"]], cfg)
        except PlanError as e:
            outcome.refused[_reason(e)] += 1
            continue
        match = check.against_source(plan, drawing, house.plan, cfg.data.resplan)
        house = house.model_copy(update={"matched": match.clean})
        _write(cfg.data.resplan.paths.out_dir, house, drawing.text)
        outcome.checks.append(match)
        outcome.done.append(house)
    return outcome


def convert_house(plan: dict, split: Split, cfg: Config) -> tuple[House, convert.Drawing]:
    """План ResPlan → SVG GenPlan → препроцессор шага 2 → метры ResPlan."""
    rules = cfg.data.resplan
    drawing = convert.svg(plan, cfg)
    raw = preprocess(drawing.text, Mode.WITH_OPENINGS, cfg.plan)
    # Препроцессор берёт масштаб GenPlan — по ширине входа 0,9 м; у ResPlan он свой, по
    # площади. Пиксель SVG здесь — 1 / px_per_m метра, к нему план и приводится.
    metric = scaled(raw, 1 / cfg.synthetic.canvas.px_per_m / raw.scale_m_per_px)
    house = House(id=house_id(plan["id"]), resplan_id=plan["id"], split=split,
                  layers=_layers(plan, rules.house_layers), area_m2=float(plan["area"]),
                  plan=metric)
    return house, drawing


def scaled(plan: Plan, k: float) -> Plan:
    """Тот же план с метрами, умноженными на k."""
    def rect(r: Rect) -> Rect:
        return Rect(x0_m=r.x0_m * k, y0_m=r.y0_m * k, x1_m=r.x1_m * k, y1_m=r.y1_m * k)

    def side(s: Side) -> Side:
        return s.model_copy(update={
            "length_m": s.length_m * k,
            "openings": [o.model_copy(update={"x_m": o.x_m * k, "width_m": o.width_m * k})
                         for o in s.openings],
            "forbidden": [ForbiddenZone(x0_m=z.x0_m * k, x1_m=z.x1_m * k) for z in s.forbidden],
        })

    return plan.model_copy(update={
        "walls": [rect(w) for w in plan.walls],
        "outline": [(x * k, y * k) for x, y in plan.outline],
        "openings": [o.model_copy(update={"rect": rect(o.rect)}) for o in plan.openings],
        "sides": [side(s) for s in plan.sides],
        "scale_m_per_px": plan.scale_m_per_px * k,
    })


def _layers(plan: dict, keys: list[str]) -> list[str]:
    return [k for k in keys if plan.get(k) is not None and not plan[k].is_empty]


def _reason(e: PlanError) -> str:
    """Причина отказа без чисел конкретного плана — чтобы отказы складывались по видам."""
    return re.sub(r"\(?-?\d[\d.]*(, -?\d[\d.]*)?\)?( px)?", "N", str(e).split(":")[0])


def _write(out: Path, house: House, svg: str) -> None:
    (out / f"{house.id}.json").write_text(house.model_dump_json(indent=1))
    (out / SVG_DIR / f"{house.id}.svg").write_text(svg)


def _write_manifest(out: Path, summary: dict, cfg: Config) -> Path:
    path = out / MANIFEST
    meta = {"settings": cfg.data.resplan.model_dump(mode="json"),
            "date": datetime.now().isoformat(timespec="seconds"), "git_sha": git_sha()}
    path.write_text(json.dumps(summary | meta, ensure_ascii=False, indent=2))
    return path
