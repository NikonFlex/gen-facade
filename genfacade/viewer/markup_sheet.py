"""Листы домов для страницы правки разметки (gf#348): страница PDF → сжатый JPEG для браузера.

Разметка записана в pt страницы PDF, а страница чертежа — одна картинка на всю страницу. Берём
саму картинку из PDF (не растрируем), сжимаем до `image_max_side` и кладём в кэш; страница рисует
её в размере страницы PDF, поэтому координаты разметки остаются теми же.
"""

import io
from pathlib import Path

import pdfplumber
from PIL import Image

from genfacade.config import Config
from genfacade.datasets.manual import Markup
from genfacade.schema import Refusal, Refused


def pdf_path(cfg: Config, m: Markup) -> Path:
    editor = cfg.viewer.markup
    return cfg.data.manual.paths.pdf_dirs[editor.source] / m.pdf


def _page(pdf: Path, number: int) -> pdfplumber.page.Page:
    """Страница PDF; нет файла или страницы — отказ с причиной."""
    if not pdf.exists():
        raise Refused(Refusal.NO_MARKUP_SHEET, f"нет файла {pdf}")
    doc = pdfplumber.open(pdf)
    if not 1 <= number <= len(doc.pages):
        raise Refused(Refusal.NO_MARKUP_SHEET, f"в {pdf.name} нет страницы {number}")
    return doc.pages[number - 1]


def plan_image(cfg: Config, m: Markup) -> Path:
    """Страница плана рядом с листом дома (`plan_image`); нет файла — отказ с причиной."""
    file = pdf_path(cfg, m).parent / cfg.viewer.markup.plan_image
    if not file.exists():
        raise Refused(Refusal.NO_MARKUP_SHEET, f"нет файла {file}")
    return file


def page_size(cfg: Config, m: Markup, number: int) -> tuple[float, float]:
    """Размер страницы в pt: в нём записана разметка."""
    page = _page(pdf_path(cfg, m), number)
    return (float(page.width), float(page.height))


def page_image(cfg: Config, m: Markup, number: int) -> Path:
    """Сжатая картинка страницы в кэше; кэш старше PDF обновляется."""
    editor, pdf = cfg.viewer.markup, pdf_path(cfg, m)
    out = editor.cache_dir / f"{m.id}-p{number}-{editor.image_max_side}.jpg"
    if out.exists() and out.stat().st_mtime >= pdf.stat().st_mtime:
        return out
    page = _page(pdf, number)
    if not page.images:
        raise Refused(Refusal.NO_MARKUP_SHEET, f"на стр. {number} листа {pdf.name} нет картинки")
    img = Image.open(io.BytesIO(page.images[0]["stream"].get_data()))
    # JPEG распаковывается сразу уменьшенным: листы бывают по 150 Мпикс
    img.draft("RGB", (editor.image_max_side, editor.image_max_side))
    img = img.convert("RGB")
    img.thumbnail((editor.image_max_side, editor.image_max_side))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=88)
    return out


def ink_box(cfg: Config, m: Markup, number: int) -> list[float]:
    """Рамка рисунка на странице, pt: всё темнее бумаги (`ink_level`). Окно вида стороны — по ней,
    чтобы фасад был виден весь, от земли до трубы; листа без рисунка — вся страница."""
    width, height = page_size(cfg, m, number)
    with Image.open(page_image(cfg, m, number)) as img:
        dark = img.convert("L").point(lambda v: 255 if v < cfg.viewer.markup.ink_level else 0)
        found = dark.getbbox()
        scale = (width / img.width, height / img.height)
    if found is None:
        return [0.0, 0.0, width, height]
    x0, y0, x1, y1 = found
    return [x0 * scale[0], y0 * scale[1], x1 * scale[0], y1 * scale[1]]
