"""Форма параметров дома для стаба шага 1 (gf#356): параметры ↔ текст описания.

Модуль принимает план и текст (`pipeline.PlanRun`), поэтому параметры из формы смотрелки уходят
в модуль текстом — словами из `config/models.toml` ([spec.*_words]), теми же, по которым стаб
читает текст обратно. «Разобрать в параметры» — стаб шага 1 (`stub.spec_model`) и чтение его ответа
(`form_of`): форма и текст не расходятся, потому что у них один список слов.

Что в форме — только то, что стаб умеет читать из слов: этажи, нижнее крыло, стиль, вид стен и
цвет стен, вид и цвет крыши, элементы есть/нет. Уклон — по виду крыши (`roof_shape`), вид двери и
модель шага 4 стаб не принимает.
"""

from genfacade.config import SpecStub
from genfacade.models import stub
from genfacade.schema import HouseSpec, Model, PaletteRole, RoofKind, Trim


class HouseForm(Model):
    """Что названо про дом; None / нет в trims — не названо, решает стаб."""

    floors: int | None = None
    wing_floors: int | None = None
    style: str | None = None
    walls: str | None = None         # вид материала стен (ключ material_words)
    wall_color: str | None = None    # имя цвета из ряда colors
    roof: RoofKind | None = None
    roof_color: str | None = None
    trims: dict[Trim, bool] = {}     # True — есть, False — «без …»


class Color(Model):
    name: str
    hex: str


class Choices(Model):
    """Что можно выбрать в форме: берётся из конфига стаба, а не из страницы."""

    floors: list[int]
    wing_floors: list[int]
    styles: list[str]
    walls: list[str]
    wall_colors: dict[str, list[Color]]  # вид стен → цвета, которые для него можно назвать
    roofs: list[RoofKind]
    roof_colors: list[Color]
    trims: list[Trim]
    pitch_deg: dict[RoofKind, float]     # уклон по виду крыши — только показать


def choices(cfg: SpecStub) -> Choices:
    walls = [k for k in cfg.material_words if _main_kinds(cfg) & {k}]
    return Choices(
        floors=list(cfg.floors_words), wing_floors=list(cfg.wing_words),
        styles=list(cfg.style_words), walls=walls,
        wall_colors={k: _wall_colors(k, cfg) for k in walls},
        roofs=list(cfg.roof_words), roof_colors=_roof_colors(cfg), trims=list(cfg.trim_words),
        pitch_deg={k: v for k, v in cfg.roof_shape.pitch_deg.items()})


def text(form: HouseForm, cfg: SpecStub) -> str:
    """Описание словами конфига. Порядок важен: цвет красит роль слова, что стоит за ним не дальше
    `reach` слов (models/finish.py), поэтому цвет стен — в конце, после всех слов других ролей."""
    parts = [_house(form, cfg), _wing(form, cfg), _roof(form, cfg), *_trims(form, cfg),
             _walls(form, cfg)]
    return ", ".join(p for p in parts if p)


def parse(description: str, cfg: SpecStub) -> HouseForm:
    """Описание → параметры: ответ стаба шага 1, прочитанный в поля формы."""
    return form_of(stub.spec_model(description, cfg), cfg)


def form_of(spec: HouseSpec, cfg: SpecStub) -> HouseForm:
    main = next(m for m in spec.materials if m.id == PaletteRole.MAIN)
    roof = next(m for m in spec.materials if m.id == PaletteRole.ROOF)
    return HouseForm(
        floors=spec.floors, wing_floors=spec.wing_floors, style=spec.style, walls=main.kind,
        wall_color=_named(main.color, cfg),
        roof=spec.roof.kind, roof_color=_named(roof.color, cfg),
        trims={t: spec.trim.has(t) for t in Trim})


def _main_kinds(cfg: SpecStub) -> set[str]:
    return {f.materials[PaletteRole.MAIN].kind for f in cfg.finish.values()}


def _wall_colors(kind: str, cfg: SpecStub) -> list[Color]:
    names = [c for f in cfg.finish.values() if f.materials[PaletteRole.MAIN].kind == kind
             for c in [*f.materials[PaletteRole.MAIN].colors, *f.materials[PaletteRole.MAIN].extra]]
    return _named_colors(dict.fromkeys(names), cfg)


def _roof_colors(cfg: SpecStub) -> list[Color]:
    """Крыше стаб красит любой цвет ряда (finish._color): кроме цветов отделки — весь ряд."""
    return _named_colors(cfg.colors, cfg)


def _named_colors(names, cfg: SpecStub) -> list[Color]:
    """Цвета, которые можно назвать словом: есть слова текста и свой цвет. Цвет в форме — это
    слово («brown»): у слова несколько имён ряда (brown, roof_brown), и какое из них возьмёт
    отделка, решает её ряд, поэтому образец — цвет первого имени, а в форме остаётся слово."""
    found: dict[str, Color] = {}
    for n in names:
        if cfg.colors[n].words and cfg.colors[n].hex:
            word = _word(cfg.colors[n].words)
            found.setdefault(word, Color(name=word, hex=cfg.colors[n].hex))
    return list(found.values())


def _named(hex_: str | None, cfg: SpecStub) -> str | None:
    """Слово цвета, которым назван цвет ответа стаба (любое имя ряда с таким цветом)."""
    return next((_word(c.words) for c in cfg.colors.values() if c.words and c.hex == hex_), None)


def _word(variants: list[str]) -> str:
    """Слово для текста: первое латиницей — текст получается одним языком."""
    return next((w for w in variants if w.isascii()), variants[0])


def _join(*words: str) -> str:
    return " ".join(w for w in words if w)


def _house(form: HouseForm, cfg: SpecStub) -> str:
    floors = _word(cfg.floors_words[form.floors]) if form.floors else ""
    style = _word(cfg.style_words[form.style]) if form.style else ""
    return _join(floors, style, "house") if floors or style else ""


def _wing(form: HouseForm, cfg: SpecStub) -> str:
    return _join("with", _word(cfg.wing_words[form.wing_floors])) if form.wing_floors else ""


def _roof(form: HouseForm, cfg: SpecStub) -> str:
    if form.roof:
        return _join((form.roof_color or ''), _word(cfg.roof_words[form.roof]))
    return _join((form.roof_color or ''), "roof") if form.roof_color else ""


def _trims(form: HouseForm, cfg: SpecStub) -> list[str]:
    no = _word(cfg.negations)
    return [_join("" if on else no, _word(cfg.trim_words[t])) for t, on in form.trims.items()]


def _walls(form: HouseForm, cfg: SpecStub) -> str:
    if not (form.walls or form.wall_color):
        return ""
    return _join((form.wall_color or ''),
                 _word(cfg.material_words[form.walls]) if form.walls else "", "walls")
