"""Общие помощники тестов над листом."""

from genfacade.schema import FacadeSheet


def with_kind(house: FacadeSheet, material: str, kind: str) -> FacadeSheet:
    """Копия листа, у которого материал палитры `material` — другого вида."""
    sheet = house.model_copy(deep=True)
    next(m for m in sheet.spec.materials if m.id == material).kind = kind
    return sheet
