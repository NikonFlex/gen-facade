"""Покрытие плана кровлей — для тестов крыши: проекция граней и площадь контура без кровли."""

import shapely

from genfacade import roof


def projection(house: roof.HouseRoof) -> shapely.Geometry:
    """Проекция всех граней кровли на план."""
    return shapely.union_all([shapely.Polygon([(x, y) for x, y, _ in face]).buffer(0)
                              for face in roof.house_faces(house)])


def uncovered(house: roof.HouseRoof) -> float:
    """Площадь контура дома, над которой нет ни одной грани кровли."""
    return shapely.Polygon(house.corners).difference(projection(house)).area
