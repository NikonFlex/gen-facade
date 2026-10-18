"""OBJ модели BuildingNet v1 и метки её компонентов.

В OBJ каждый объект `o <номер>` — компонент (окно целиком, кусок стены), его метка — в
`component_labels/<модель>_label.json` архива меток: номер компонента → номер метки. Y — вверх.
"""

import json
import zipfile
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

import numpy


class Label(StrEnum):
    """Метки частей BuildingNet в порядке их номеров (`toplabels` в GNN/utils/IOU.py их репо)."""

    UNDETERMINED = "undetermined"
    WALL = "wall"
    WINDOW = "window"
    VEHICLE = "vehicle"
    ROOF = "roof"
    PLANT_TREE = "plant_tree"
    DOOR = "door"
    TOWER_STEEPLE = "tower_steeple"
    FURNITURE = "furniture"
    GROUND_GRASS = "ground_grass"
    BEAM_FRAME = "beam_frame"
    STAIRS = "stairs"
    COLUMN = "column"
    RAILING_BALUSTER = "railing_baluster"
    FLOOR = "floor"
    CHIMNEY = "chimney"
    CEILING = "ceiling"
    FENCE = "fence"
    POND_POOL = "pond_pool"
    CORRIDOR_PATH = "corridor_path"
    BALCONY_PATIO = "balcony_patio"
    GARAGE = "garage"
    DOME = "dome"
    ROAD = "road"
    ENTRANCE_GATE = "entrance_gate"
    PARAPET_MERLON = "parapet_merlon"
    BUTTRESS = "buttress"
    DORMER = "dormer"
    LANTERN_LAMP = "lantern_lamp"
    ARCH = "arch"
    AWNING = "awning"
    SHUTTERS = "shutters"


LABELS = list(Label)


class Component(NamedTuple):
    """Часть модели: метка, вершины (n × 3) и грани — тройки номеров этих вершин."""

    label: Label
    vertices: numpy.ndarray
    faces: numpy.ndarray


def labels(archive: Path, model: str) -> dict[str, Label]:
    """Номер компонента → метка."""
    with zipfile.ZipFile(archive) as z:
        raw = json.loads(z.read(f"component_labels/{model}_label.json"))
    return {k: LABELS[int(v)] for k, v in raw.items()}


def read(path: Path, marks: dict[str, Label]) -> list[Component]:
    """Компоненты OBJ; многоугольные грани режутся веером на треугольники."""
    points, groups, current = [], {}, None
    for line in path.read_text(errors="ignore").splitlines():
        head, _, rest = line.partition(" ")
        if head == "v":
            points.append([float(t) for t in rest.split()[:3]])
        elif head == "o":
            current = groups.setdefault(rest.strip(), [])
        elif head == "f" and current is not None:
            ids = [int(t.split("/")[0]) - 1 for t in rest.split()]
            current += [(ids[0], a, b) for a, b in zip(ids[1:], ids[2:], strict=False)]
    vertices = numpy.array(points)  # один раз на модель, а не на каждый из тысяч компонентов
    return [_component(vertices, name, tris, marks) for name, tris in groups.items() if tris]


def _component(points: numpy.ndarray, name: str, tris: list, marks: dict[str, Label]) -> Component:
    used, faces = numpy.unique(numpy.array(tris), return_inverse=True)
    return Component(marks.get(name, Label.UNDETERMINED), points[used],
                     faces.reshape(-1, 3))
