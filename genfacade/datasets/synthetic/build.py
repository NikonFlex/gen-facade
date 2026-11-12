"""Пример датасета по seed: план → препроцессор → параметры дома → раскладка стен."""

import random

import shapely

from genfacade import derive, parts, pipeline, roof
from genfacade.config import Config, Parts, Synthetic
from genfacade.datasets import genplan_writer
from genfacade.datasets.synthetic import (
    contour,
    decor,
    gable,
    openings,
    roofs,
    sizes,
    upper,
    zones,
)
from genfacade.datasets.synthetic.house import Look, house
from genfacade.plan.preprocess import preprocess
from genfacade.schema import (
    EPS,
    Element,
    FacadeSheet,
    GuidelineCheck,
    GuidelineUse,
    HouseSpec,
    Mode,
    Placement,
    Sample,
    SideFacade,
    Source,
    Split,
)


def sample_id(seed: int) -> str:
    return f"rect-{seed:06d}"


def split(seed: int, rules: Synthetic) -> Split:
    """Часть датасета — по seed, а не по порядку сборки: дом всегда в одной и той же части."""
    draw = random.Random(f"split/{seed}").random()  # noqa: S311 — не криптография
    return Split.VAL if draw < rules.build.val_share else Split.TRAIN


def with_norms(cfg: Config) -> Config:
    """Настройки генератора с нормами стража из свода (gf#212): эталон корпуса не нарушает норм,
    которые страж держит при генерации, — иначе страж его обрывает. Число — в правиле свода."""
    on = {g.check: g.params for g in cfg.guidelines.guideline if GuidelineUse.GUARD in g.use}
    corner = on.get(GuidelineCheck.CORNER_DISTANCE, {}).get("min", 0.0)
    syn = cfg.synthetic
    openings = syn.openings.model_copy(update={"window_corner_m": corner})
    return cfg.model_copy(update={"synthetic": syn.model_copy(update={"openings": openings})})


def sample(seed: int, cfg: Config) -> Sample:
    cfg = with_norms(cfg)
    syn = cfg.synthetic
    svg = genplan_writer.svg(contour.draft(seed, syn), syn.canvas)
    floor = preprocess(svg, Mode.WITH_OPENINGS, cfg.plan).model_copy(
        update={"source": Source.SYNTHETIC})
    # Свой поток случайных чисел: правка правил плана не меняет параметры дома, и наоборот.
    spec, look = house(random.Random(f"house/{seed}"), cfg,  # noqa: S311 — не криптография
                       sizes.pick(seed, syn))
    bare = pipeline.walls(spec, floor, _lower_wings(cfg) if roofs.annexed(seed, spec, floor, cfg)
                          else None)
    if _straddled(bare):  # проём плана на ступени резать нечем: дом остаётся одной высоты
        bare = pipeline.walls(spec, floor)
    if any(f.runs for f in bare.facades):
        sheet = lay_out_parts(bare, look, cfg, seed)
    else:
        sheet = lay_out(bare, look, cfg, random.Random(f"upper/{seed}"),  # noqa: S311
                        random.Random(f"gable/{seed}"))  # noqa: S311 — не криптография
    # Крыши частей и щипец — после раскладки и со своим потоком: стены от них не зависят.
    sheet = roofs.compose(random.Random(f"roofs/{seed}"), sheet, cfg)  # noqa: S311
    return Sample(id=sample_id(seed), source=Source.SYNTHETIC, split=split(seed, syn),
                  plan=floor, sheet=sheet)


def _straddled(sheet: FacadeSheet) -> bool:
    """Проём плана лежит на границе участков стены: его пришлось бы резать, а окно получило бы
    свой типоразмер и торчало бы за силуэт."""
    return any(parts.clamped(o, f.runs).width_m < o.width_m - EPS
               for f in sheet.facades for o in f.side.openings)


def _lower_wings(cfg: Config) -> Parts:
    """Правило частей для дома с пристройкой: нижнее крыло — по `[parts]`; крышу пристройки ставит
    `roofs.compose` (свой уклон по жребию), а не правило генерации."""
    return cfg.plan.parts.model_copy(update={"annex_shed": False})


def lay_out_parts(sheet: FacadeSheet, look: Look, cfg: Config, seed: int) -> FacadeSheet:
    """Раскладка дома из частей разной высоты: части одной этажности — «дом» для раскладки, как у
    модели в конвейере (`pipeline._layout_parts`); окон во фронтоне у такого дома нет."""
    subs = parts.sub_sheets(sheet)
    place = _placer(random.Random(f"upper/{seed}"), sheet, look, cfg)  # noqa: S311
    done = {n: lay_out(sub, look, cfg, random.Random(f"upper/{seed}/{n}"), place=place)  # noqa: S311
            for n, (sub, _) in subs.items()}
    merged = parts.merge(sheet, done, {n: pcs for n, (_, pcs) in subs.items()})
    return merged.model_copy(update={"facades": [f.model_copy(update={
        "elements": [_on_mm(e) for e in f.elements]}) for f in merged.facades]})


def _on_mm(e: Element) -> Element:
    """Элемент на миллиметрах: участок стороны режет проём вычитанием, и ширина окна выходит с
    шумом 1e-16 — один типоразмер окна считался бы двумя (`generation: Типоразмеры окон дома`)."""
    return e.model_copy(update={"x_m": round(e.x_m, 3), "w_m": round(e.w_m, 3)})


def _placer(rng: random.Random, sheet: FacadeSheet, look: Look, cfg: Config) -> openings.Placer:
    """Расстановка окон по вертикали: типоразмеры — на дом по ширинам окон плана `sheet`."""
    return (openings.scattered(rng, sheet, look, cfg)
            if cfg.synthetic.openings.placement is Placement.RANDOM
            else openings.on_head_line(look, cfg.synthetic.facade.windows))


def lay_out(sheet: FacadeSheet, look: Look, cfg: Config, rng: random.Random,
            roof_rng: random.Random | None = None,
            place: openings.Placer | None = None) -> FacadeSheet:
    """Раскладка всех стен дома при одних параметрах и одном характере; rng — окна верхних
    этажей, которых нет в плане; roof_rng — окна во фронтоне (gf#321), None — без них; place —
    расстановка окон по вертикали, общая у частей дома (типоразмеры окон — на дом)."""
    spec, windows = sheet.spec, cfg.synthetic.facade.windows
    place = place or _placer(rng, sheet, look, cfg)
    placed = []
    for f in sheet.facades:
        rows = upper.rows(rng, f.side, spec.floors, cfg)
        placed.append(f.model_copy(update={
            "elements": openings.windows(rows, spec, place, windows)}))
    storeys = sheet.model_copy(update={"facades": placed})
    over = (gable.windows(roof_rng, storeys, cfg) if roof_rng is not None
            else [[] for _ in placed])
    above = roof.gables(storeys)
    # стена с окнами во фронтоне — щипцовая, карниза на ней нет (`facade: Карниз под скатом`)
    walls = [_wall(f.model_copy(update={"elements": [*f.elements, *extra]}), spec, look, cfg,
                   cornice=not extra,
                   shape=roof.wall_shape(f.side.length_m, spec.eaves_m, up) if extra else None)
             for f, extra, up in zip(placed, over, above, strict=True)]
    return sheet.model_copy(update={"facades": walls})


def _wall(wall: SideFacade, spec: HouseSpec, look: Look, cfg: Config,
          cornice: bool = True, shape: shapely.Geometry | None = None) -> SideFacade:
    """Стена с уже поставленными окнами (`wall.elements`) — дверь, декор и зоны. Подоконники,
    наличники, ставни и козырёк правило только отмечает у проёма, ставит их код (derive.py)."""
    rules, side, windows = cfg.synthetic.facade, wall.side, wall.elements
    doors = openings.doors(side, spec, look, rules)
    porch = look.porch and spec.plinth_m > 0  # крыльцо — на высоту цоколя: без цоколя его нет
    porches = [decor.porch(d, spec, cfg.checks.porch_pad_m) for d in doors] if porch else []
    ctx = derive.Wall(spec, side.length_m, cfg.derive)
    laid = [*windows, *doors, *porches,
            *([decor.cornice(side.length_m, spec, look.cornice_m)] if cornice else [])]
    elements = derive.place(laid, decor.flags(windows, doors, ctx, shape), ctx)
    placed = wall.model_copy(update={"elements": elements})
    return placed.model_copy(update={"zones": zones.zones(placed, spec, look, rules.finish)})
