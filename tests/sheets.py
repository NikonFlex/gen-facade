"""Общие помощники тестов над листом."""

from genfacade.schema import FacadeSheet


def with_kind(house: FacadeSheet, material: str, kind: str) -> FacadeSheet:
    """Копия листа, у которого материал палитры `material` — другого вида."""
    sheet = house.model_copy(deep=True)
    next(m for m in sheet.spec.materials if m.id == material).kind = kind
    return sheet


def with_foreign_parts(sheet: FacadeSheet) -> FacadeSheet:
    """Лист старой сборки: крыльев в нём нет, а номера частей в участках — от другой нарезки."""
    return sheet.model_copy(update={"wings": [], "facades": [
        f.model_copy(update={"runs": [r.model_copy(update={"part": r.part + 2}) for r in f.runs]})
        for f in sheet.facades]})
