"""Вкладка «Каталог» смотрелки (/catalog, gf#354): какие вообще бывают материалы, цвета, крыши,
окна, двери и выводимые элементы.

Состав берётся из конфига и перечислений схемы, а не из списка на странице: новый вид,
добавленный записью (library.toml, models.toml, derive.toml), появляется в выдаче сам. Картинка
вида — тем же render/svg.py, что лист (samples.py); слова текста — models.toml; источник —
таблицы docs/library-catalog.md (catalog_doc.py). Страница ничего не считает: она получает разделы
и рисует их как есть. Разделы и их порядок — config/viewer.toml, [catalog.sections.*].
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from functools import partial

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from genfacade import schema
from genfacade.config import Config, FinishRole
from genfacade.schema import (
    DOOR_KINDS,
    ElementClass,
    HouseSpec,
    HouseTrim,
    Material,
    OpeningVariant,
    PaletteRole,
    Refusal,
    RoofKind,
    Trim,
    VariantKind,
    refusal_record,
)
from genfacade.viewer import catalog_doc, samples

BLANK = "blank"  # дверь без остекления — не вид, а его отсутствие; в URL нужно имя
NO_KIND = "none"  # вид «элемента у дома нет»: в каталоге не вид
# Пока вид выводимого элемента — enum в schema.py (gf#318 заменяет его записями derive.toml),
# его члены — виды; когда перечисления не станет, виды берёт Derive.kinds и этот путь можно убрать.
KIND_ENUMS = {Trim.SILL: "SillKind", Trim.CASING: "CasingKind", Trim.SHUTTERS: "ShutterKind",
              Trim.CANOPY: "CanopyKind"}


@dataclass(frozen=True)
class Item:
    """Вид в каталоге. words — слова текста, выбирающие именно его; shared — слова общего вида,
    которые называют и его («кирпич» называет и полуторный); facts — строки «подпись — значение»."""

    name: str
    title: str
    draw: Callable[[], str]
    group: str = ""
    words: tuple[str, ...] = ()
    shared: tuple[str, ...] = ()
    source: str = ""
    facts: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    note: str
    words: tuple[str, ...]  # слова, которыми текст называет сам элемент (подоконник, ставни)
    items: list[Item]


Built = tuple[list[Item], tuple[str, ...]]
Source = dict[str, str]


def section(cfg: Config, sid: str) -> Section:
    """Один раздел каталога; идентификатор — ключ [catalog.sections.*] конфига."""
    catalog = cfg.viewer.catalog
    if sid not in BUILDERS:
        raise ValueError(f"[catalog.sections.{sid}]: нет построителя")
    text = catalog.sections[sid]
    found = catalog_doc.sources(catalog.doc, text.doc_headings, text.doc_row)
    items, words = BUILDERS[sid](cfg, found)
    return Section(sid, text.title, text.note, words, items)


def sections(cfg: Config) -> list[Section]:
    """Все разделы каталога в порядке конфига."""
    return [section(cfg, sid) for sid in cfg.viewer.catalog.sections]


def listing(cfg: Config) -> dict:
    """Ответ /api/catalog: разделы с видами; картинка — адресом, а не SVG в тексте."""
    return {"sections": [{
        "id": s.id, "title": s.title, "note": s.note, "words": list(s.words), "count": len(s.items),
        "items": [{"name": i.name, "title": i.title, "group": i.group, "words": list(i.words),
                   "shared": list(i.shared), "source": i.source,
                   "facts": [{"label": k, "value": v} for k, v in i.facts],
                   "image": f"/api/catalog/{s.id}/{i.name}/image.svg"} for i in s.items],
    } for s in sections(cfg)]}


def api(app: FastAPI, cfg: Config) -> None:
    @app.get("/api/catalog")
    def catalog() -> dict:
        return listing(cfg)

    @app.get("/api/catalog/{section_id}/{name}/image.svg")
    def image(section_id: str, name: str) -> Response:
        item = _find(cfg, section_id, name)
        try:
            return Response(item.draw(), media_type="image/svg+xml")
        except (ValueError, KeyError) as e:  # вид есть в конфиге, а схема его не принимает
            raise HTTPException(422, refusal_record(Refusal.CATALOG_NOT_DRAWN, str(e))) from e


def _find(cfg: Config, section_id: str, name: str) -> Item:
    if section_id in cfg.viewer.catalog.sections:
        for item in section(cfg, section_id).items:
            if item.name == name:
                return item
    raise HTTPException(404, refusal_record(Refusal.NO_CATALOG_ITEM, f"{section_id}/{name}"))


# ——— материалы, цвета, отделки ———

def _walls(cfg: Config, found: Source) -> Built:
    return [_material(cfg, k, found, partial(_wall_view, cfg, k, None))
            for k in _wall_kinds(cfg)], ()


def _roofing(cfg: Config, found: Source) -> Built:
    return [_material(cfg, k, found, partial(_roof_view, cfg, k, None))
            for k in _roof_kinds(cfg)], ()


def _made(cfg: Config) -> Iterator[tuple[str, PaletteRole, FinishRole]]:
    """Материалы всех отделок: имя отделки, роль палитры и что в ней стоит."""
    for name, finish in cfg.models.spec.finish.items():
        for role, made in finish.materials.items():
            yield name, role, made


def _roles(cfg: Config) -> dict[str, set[PaletteRole]]:
    """Вид материала → роли палитры, на которые его ставит хотя бы одна отделка."""
    out: dict[str, set[PaletteRole]] = {}
    for _, role, made in _made(cfg):
        out.setdefault(made.kind, set()).add(role)
    return out


def _roof_kinds(cfg: Config) -> list[str]:
    return [k for k, roles in _roles(cfg).items() if PaletteRole.ROOF in roles]


def _wall_kinds(cfg: Config) -> list[str]:
    """Виды для стен: все, что кроме тех, которые отделки ставят только на крышу; вид, которого
    нет ни в одной отделке (добавлен записью в library.toml), — стеновой."""
    roles, kinds = _roles(cfg), cfg.library.kinds
    return [k for k in kinds if roles.get(k, {PaletteRole.MAIN}) - {PaletteRole.ROOF}]


def _material(cfg: Config, kind: str, found: Source, draw: Callable[[], str]) -> Item:
    spec, lib, label = cfg.models.spec, cfg.library, cfg.viewer.catalog.labels
    like = spec.material_like.get(kind)
    facts = [(label["color"], lib.kinds[kind]), (label["pattern"], _pattern(cfg, kind))]
    if kind in lib.model_kinds:
        facts.append((label["model_sees"], lib.model_kinds[kind]))
    return Item(kind, kind, draw, words=tuple(spec.material_words.get(kind, ())),
                shared=tuple(spec.material_words.get(like, ())) if like else (),
                source=found.get(kind, ""), facts=tuple(facts))


def _pattern(cfg: Config, kind: str) -> str:
    label, hatch = cfg.viewer.catalog.labels, cfg.library.patterns.get(kind)
    if hatch is None:
        return label["solid"]
    return label["pattern_value"].format(course=f"{sum(c.h_m for c in hatch.courses):g}",
                                         width=f"{hatch.width_m:g}", line=f"{hatch.line_m:g}")


def _house_view(cfg: Config, materials: list[Material], roof: RoofKind, trim: HouseTrim) -> str:
    """Дом образца в этих материалах: фронтон с окном и входом, кровля, виды элементов дома."""
    spec = samples.with_materials(samples.default_spec(cfg), *materials)
    spec = spec.model_copy(update={
        "roof": cfg.models.spec.roof_shape.roof(roof, PaletteRole.ROOF), "trim": trim})
    look = cfg.viewer.catalog.sample
    view = samples.View(spec, (look.width_m, look.depth_m), side=1,
                       trims=frozenset(t for t in Trim if trim.has(t)))
    return samples.render(cfg, replace(view, openings=(
        samples.window(cfg, view, look.window_at), samples.door(cfg, view, look.door_at))))


def _wall_view(cfg: Config, kind: str, color: str | None, role: PaletteRole = PaletteRole.MAIN
               ) -> str:
    """Стена образца с окном: материал вида (и цвета) в роли role."""
    spec = samples.default_spec(cfg)
    spec = samples.with_materials(spec, samples.role_material(spec, role, kind=kind, color=color))
    return _one_opening(cfg, spec, ElementClass.WINDOW)


def _roof_view(cfg: Config, kind: str, color: str | None) -> str:
    """Скат двускатного дома образца (длинная сторона) — на нём виден рисунок кровли."""
    spec = samples.default_spec(cfg)
    spec = samples.with_materials(spec, samples.role_material(spec, PaletteRole.ROOF, kind=kind,
                                                            color=color))
    return _roof_house(cfg, spec, RoofKind.GABLE, side=0)


def _roof_house(cfg: Config, spec: HouseSpec, kind: RoofKind, side: int) -> str:
    """Дом образца с крышей вида kind, в кадре сторона side: фронтон (1) или скат (0)."""
    spec = spec.model_copy(update={"roof": cfg.models.spec.roof_shape.roof(kind, PaletteRole.ROOF)})
    look = cfg.viewer.catalog.sample
    return samples.render(cfg, samples.View(spec, (look.width_m, look.depth_m), side=side))


def _colors(cfg: Config, found: Source) -> Built:
    uses, label = _color_uses(cfg), cfg.viewer.catalog.labels
    items = []
    for name, color in cfg.models.spec.colors.items():
        role, kind = uses.get(name, (PaletteRole.MAIN, _main_kind(cfg)))
        hex_ = color.hex or cfg.library.kinds[kind]
        view = _roof_view if role is PaletteRole.ROOF else _wall_view
        used = ", ".join(_finishes_of(cfg, name)) or label["none"]
        facts = ((label["hex"], hex_), (label["used_in"], used))
        items.append(Item(name, name, partial(view, cfg, kind, hex_), words=tuple(color.words),
                          facts=facts))
    return items, ()


def _main_kind(cfg: Config) -> str:
    spec = cfg.models.spec
    return spec.finish[spec.default_finish].materials[PaletteRole.MAIN].kind


def _finishes_of(cfg: Config, color: str) -> list[str]:
    return sorted({name for name, _, made in _made(cfg) if color in (*made.colors, *made.extra)})


def _color_uses(cfg: Config) -> dict[str, tuple[PaletteRole, str]]:
    """Цвет → роль и вид материала, в которых его впервые ставит отделка: на этом образце цвет
    и рисуется (кровельный цвет — на кровле)."""
    out: dict[str, tuple[PaletteRole, str]] = {}
    for _, role, made in _made(cfg):
        for color in (*made.colors, *made.extra):
            out.setdefault(color, (role, made.kind))
    return out


def _schemes(cfg: Config, found: Source) -> Built:
    items = []
    for name, scheme in cfg.models.spec.schemes.items():
        materials = [_painted(cfg, role, cfg.models.spec.colors[c].hex)
                     for role, c in scheme.colors.items()]
        trim = _plain_trim(cfg)
        draw = partial(_house_view, cfg, materials, RoofKind.GABLE, trim)
        label = cfg.viewer.catalog.labels
        facts = tuple((label[f"role_{role}"], f"{c} {cfg.models.spec.colors[c].hex or ''}".strip())
                      for role, c in scheme.colors.items())
        items.append(Item(name, name, draw, source=scheme.source, facts=facts))
    return items, ()


def _plain_trim(cfg: Config) -> HouseTrim:
    """Наличник и подоконник по умолчанию: в сочетании виден цвет роли trim."""
    default = cfg.models.spec.trim_default
    return HouseTrim(sill=default.sill, casing=default.casing)


def _painted(cfg: Config, role: PaletteRole, color: str | None) -> Material:
    """Материал роли в палитре образца с этим цветом: вид — как у дома по умолчанию."""
    return samples.role_material(samples.default_spec(cfg), role, color=color)


def _finishes(cfg: Config, found: Source) -> Built:
    spec, label = cfg.models.spec, cfg.viewer.catalog.labels
    items = []
    for name, f in spec.finish.items():
        materials = [Material(id=role, kind=made.kind, color=spec.colors[made.colors[0]].hex)
                     for role, made in f.materials.items()]
        draw = partial(_house_view, cfg, materials, f.roof, f.trim)
        facts = ((label["styles"], ", ".join(f.styles)), (label["roof"], str(f.roof)),
                 (label["trim"], _trim_text(f.trim)),
                 (label["materials"], ", ".join(f"{r}: {m.kind}" for r, m in f.materials.items())))
        items.append(Item(name, name, draw, facts=facts))
    return items, ()


def _trim_text(trim: HouseTrim) -> str:
    return ", ".join(f"{t}: {trim.kind(t)}" for t in Trim)


# ——— крыши, окна, двери, выводимые элементы, крыльцо ———

def _roofs(cfg: Config, found: Source) -> Built:
    spec = cfg.models.spec
    items = [Item(kind.value, kind.value, partial(_roof_house, cfg, samples.default_spec(cfg),
                                                  kind, 1),
                  words=tuple(spec.roof_words[kind]), source=found.get(kind.value, ""),
                  facts=_roof_facts(cfg, kind)) for kind in RoofKind]
    return items, ()


def _roof_facts(cfg: Config, kind: RoofKind) -> tuple[tuple[str, str], ...]:
    """Уклон и свес вида крыши (у плоской их нет)."""
    shape, label = cfg.models.spec.roof_shape, cfg.viewer.catalog.labels
    if kind is RoofKind.FLAT:
        return ()
    return ((label["pitch"], f"{shape.pitch_deg[kind]:g}°"),
            (label["overhang"], f"{shape.overhang_m:g}"))


def _windows(cfg: Config, found: Source) -> Built:
    labels, sizes = cfg.viewer.labels.variant, cfg.viewer.catalog.sample.window_m
    items = []
    for kind in (k for k in VariantKind if k not in DOOR_KINDS):
        w, h = sizes.get(kind, sizes["default"])
        items.append(Item(kind.value, labels.get(kind, kind.value),
                          partial(_opening_view, cfg, ElementClass.WINDOW, kind, None),
                          source=found.get(kind.value, ""),
                          facts=((cfg.viewer.catalog.labels["size"], f"{w:g} × {h:g}"),)))
    return items, ()


def _opening_view(cfg: Config, cls: ElementClass, variant: VariantKind | None,
                  leaf: str | None) -> str:
    """Стена образца с одним проёмом: окно или дверь вида variant; leaf — рисунок полотна двери."""
    spec = samples.default_spec(cfg)
    if leaf is not None:
        spec = spec.model_copy(update={"trim": HouseTrim(**{ElementClass.DOOR: leaf})})
    shape = OpeningVariant(kind=variant) if variant is not None else None
    return _one_opening(cfg, spec, cls, shape)


def _one_opening(cfg: Config, spec: HouseSpec, cls: ElementClass,
                 variant: OpeningVariant | None = None, trims: frozenset[Trim] = frozenset()
                 ) -> str:
    """Стена образца с окном или дверью посередине; trims — какие выводимые элементы поставить."""
    side = cfg.viewer.catalog.sample.wall_m
    view = samples.View(spec, (side, side), trims=trims)
    make = samples.window if cls is ElementClass.WINDOW else samples.door
    return samples.render(cfg, replace(view, openings=(make(cfg, view, variant=variant),)))


def _doors(cfg: Config, found: Source) -> Built:
    label, door = cfg.viewer.catalog.labels, ElementClass.DOOR
    items = [Item(kind, kind, partial(_opening_view, cfg, door, None, kind),
                  group=label["group_leaf"], source=found.get(kind, ""),
                  facts=_derive_facts(cfg, "door", kind), words=_kind_words(cfg, "door", kind))
             for kind in derive_kinds(cfg, "door")]
    items.append(Item(BLANK, label["blank"], partial(_opening_view, cfg, door, None, None),
                      group=label["group_glazing"]))
    items += [Item(k.value, cfg.viewer.labels.variant.get(k, k.value),
                   partial(_opening_view, cfg, door, k, None), group=label["group_glazing"])
              for k in DOOR_KINDS]
    return items, ()


def _trim_section(trim: Trim, cfg: Config, found: Source) -> Built:
    """Вид выводимого элемента (подоконник, наличник, ставни, козырёк) на окне образца, а козырёк —
    над дверью."""
    cls = ElementClass.DOOR if trim is Trim.CANOPY else ElementClass.WINDOW
    items = [Item(kind, kind, partial(_trim_view, cfg, trim, kind, cls),
                  words=_kind_words(cfg, trim, kind), source=found.get(kind, ""),
                  facts=_derive_facts(cfg, trim, kind)) for kind in derive_kinds(cfg, trim)]
    return items, tuple(cfg.models.spec.trim_words.get(trim, ()))


def _trim_view(cfg: Config, trim: Trim, kind: str, cls: ElementClass) -> str:
    spec = samples.default_spec(cfg).model_copy(update={"trim": HouseTrim(**{trim: kind})})
    return _one_opening(cfg, spec, cls, trims=frozenset({trim}))


def derive_kinds(cfg: Config, name: str) -> list[str]:
    """Виды элемента дома (sill, casing, shutters, canopy, door) без «нет»: записи derive.toml;
    пока вид — enum в schema.py, — его члены. Элемента без видов (door до gf#318) — пусто."""
    kinds = getattr(cfg.derive, "kinds", None)
    if kinds is not None:
        return list(kinds(name))
    enum = getattr(schema, KIND_ENUMS.get(name, ""), None)
    return [m.value for m in enum if m.value != NO_KIND] if enum else []


def _derive_facts(cfg: Config, name: str, kind: str) -> tuple[tuple[str, str], ...]:
    """Размеры вида как записаны в derive.toml. Запись — таблица (подоконник, козырёк), число
    (наличник: ширина доски) или общая для всех видов таблица раздела (ставни: доля окна)."""
    section = cfg.derive.model_dump(mode="json").get(name, {})
    entry = section.get(kind, section)
    if not isinstance(entry, dict):
        entry = {"width_m": entry}
    return tuple((k, f"{v:g}" if isinstance(v, float) else str(v)) for k, v in entry.items()
                 if isinstance(v, (int, float, str)) and k != "shape")


def _kind_words(cfg: Config, name: str, kind: str) -> tuple[str, ...]:
    """Слова текста, выбирающие вид элемента (`kind_words`, gf#318); таблицы нет — пусто."""
    found = cfg.models.spec.model_dump(mode="json").get("kind_words", {})
    return tuple(found.get(name, {}).get(kind, ()))


def _porch(cfg: Config, found: Source) -> Built:
    """Крыльцо: класс элемента, у которого нет видов, — один образец; размеры — те же, что у рамки
    на странице правки, выступ — как в 3D."""
    label = cfg.viewer.catalog.labels
    w, h = cfg.viewer.markup.default_size_m[ElementClass.PORCH]
    depth = cfg.viewer.house3d.relief_cls[ElementClass.PORCH]
    name = ElementClass.PORCH.value
    return [Item(name, cfg.viewer.labels.cls[ElementClass.PORCH], partial(_porch_view, cfg),
                 facts=((label["size"], f"{w:g} × {h:g}"), (label["relief"], f"{depth:g}")))], ()


def _porch_view(cfg: Config) -> str:
    side = cfg.viewer.catalog.sample.wall_m
    view = samples.View(samples.default_spec(cfg), (side, side))
    door = samples.door(cfg, view)
    w, h = cfg.viewer.markup.default_size_m[ElementClass.PORCH]
    porch = door.model_copy(update={"id": "p1", "cls": ElementClass.PORCH, "w_m": w, "h_m": h,
                                    "x_m": round((side - w) / 2, 3), "y_m": 0.0})
    return samples.render(cfg, replace(view, openings=(porch, door)))


BUILDERS: dict[str, Callable[[Config, Source], Built]] = {
    "walls": _walls, "roofing": _roofing, "colors": _colors, "schemes": _schemes,
    "finishes": _finishes, "roofs": _roofs, "windows": _windows, "doors": _doors,
    "sills": partial(_trim_section, Trim.SILL), "casings": partial(_trim_section, Trim.CASING),
    "shutters": partial(_trim_section, Trim.SHUTTERS),
    "canopies": partial(_trim_section, Trim.CANOPY), "porch": _porch,
}
