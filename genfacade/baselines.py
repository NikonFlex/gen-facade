"""Базовые подходы для таблицы метрик (`evaluation: Базовые подходы`).

Правило GenPlan (gf#141) — фасад так, как его строит GenPlan сейчас (код GenPlan, gf#34):
окна — разрывы плана, высота одна на дом, у стены одна отделка; цоколя, подоконников,
наличников и карниза нет. Разрывы — только те, что даны в условии режима: в глухом режиме окон
плана нет, и окон у правила нет.

Вход — папка листов: от каждого берутся стены, стороны с условием и параметры дома, элементы и
зоны отбрасываются. Так правило отвечает на те же дома и условия, что и модель в
`genfacade eval`.
"""

from enum import StrEnum
from pathlib import Path

from pydantic import ValidationError

from genfacade.config import Config
from genfacade.schema import (
    Element,
    ElementClass,
    FacadeSheet,
    FixedField,
    MaterialZone,
    OpeningKind,
    PaletteRole,
    SideFacade,
    ZoneRole,
)

DOORS = (OpeningKind.DOOR, OpeningKind.ENTRANCE)
FIXED = [FixedField.X, FixedField.W]


class Baseline(StrEnum):
    GENPLAN = "genplan"


def genplan(sheet: FacadeSheet, cfg: Config) -> FacadeSheet:
    return sheet.model_copy(update={"facades": [_wall(f, sheet, cfg) for f in sheet.facades]})


def _wall(f: SideFacade, sheet: FacadeSheet, cfg: Config) -> SideFacade:
    length, eaves = f.side.length_m, sheet.spec.eaves_m
    wall = MaterialZone(shape=[(0, 0), (length, 0), (length, eaves), (0, eaves)],
                        material=PaletteRole.MAIN, role=ZoneRole.MAIN)
    return f.model_copy(update={"elements": _doors(f, sheet, cfg) + _windows(f, sheet, cfg),
                                "zones": [wall]})


def _doors(f: SideFacade, sheet: FacadeSheet, cfg: Config) -> list[Element]:
    """Двери — из плана, на пол первого этажа, высотой как у синтетики."""
    return [Element(id=f"d{k + 1}", cls=ElementClass.DOOR, x_m=o.x_m, y_m=sheet.spec.plinth_m,
                    w_m=o.width_m, h_m=cfg.synthetic.facade.door.height_m, floor=1, fixed=FIXED)
            for k, o in enumerate(o for o in f.side.openings if o.kind in DOORS)]


def _windows(f: SideFacade, sheet: FacadeSheet, cfg: Config) -> list[Element]:
    """Окно плана — на каждом этаже над разрывом, низ и верх — доли высоты этажа."""
    low, high = cfg.baselines.genplan.window
    spec, out = sheet.spec, []
    gaps = [o for o in f.side.openings if o.kind is OpeningKind.WINDOW]
    for floor, (base, h) in enumerate(zip(spec.floor_levels(), spec.floor_heights_m,
                                          strict=False), start=1):
        out += [Element(id=f"w{floor}_{k + 1}", cls=ElementClass.WINDOW, x_m=o.x_m,
                        y_m=base + low * h, w_m=o.width_m, h_m=(high - low) * h, floor=floor,
                        fixed=FIXED if floor == 1 else []) for k, o in enumerate(gaps)]
    return out


RULES = {Baseline.GENPLAN: genplan}


def run(name: Baseline, source: Path, cfg: Config, out: Path) -> Path:
    """Листы папки source → фасады базового подхода с теми же именами в out."""
    out.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("*.json")):
        try:
            sheet = FacadeSheet.model_validate_json(path.read_text())
        except ValidationError:
            continue  # неразобранный ответ модели: условия дома в нём нет
        (out / path.name).write_text(RULES[name](sheet, cfg).model_dump_json())
    return out
