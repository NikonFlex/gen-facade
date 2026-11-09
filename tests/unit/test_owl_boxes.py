"""tools/owl_boxes.py (gf#342): рамки OWLv2 → JSON на дом. Модель — заглушка, сети нет."""
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from PIL import Image

from genfacade.schema import ElementClass

PATH = Path(__file__).resolve().parents[2] / "tools" / "owl_boxes.py"
SPEC = spec_from_file_location("owl_boxes", PATH)
owl = module_from_spec(SPEC)
SPEC.loader.exec_module(owl)

SIZE = (400, 300)


def stub(image):
    """Окно найдено дважды (вторая рамка слабее и вложена), дверь, щель и целая стена."""
    assert image.size == SIZE
    return [owl.Box([100, 100, 160, 180], ElementClass.WINDOW, 0.30),
            owl.Box([105, 105, 155, 175], ElementClass.WINDOW, 0.10),
            owl.Box([200, 100, 240, 180], ElementClass.DOOR, 0.20),
            owl.Box([300, 100, 302, 200], ElementClass.WINDOW, 0.50),
            owl.Box([0, 0, 400, 300], ElementClass.WINDOW, 0.90)]


def make_house(root: Path) -> Path:
    folder = root / "55001"
    folder.mkdir()
    for n in (0, 1):
        Image.new("RGB", SIZE, "white").save(folder / f"facade{n}.jpg")
    Image.new("RGB", SIZE, "white").save(folder / "plan0-0.jpg")  # план в детектор не идёт
    return folder


def test_detect_drops_duplicate_slit_and_wall():
    boxes = owl.detect(Image.new("RGB", SIZE), stub)
    assert [(b.cls, b.box[0]) for b in boxes] == [
        (ElementClass.WINDOW, 100), (ElementClass.DOOR, 200)]


def test_run_writes_json_per_house(tmp_path):
    make_house(tmp_path)
    out = tmp_path / "out"
    summary = owl.run(["55001"], tmp_path, out, lambda: stub)
    result = json.loads((out / "55001.json").read_text())
    assert [s["page"] for s in result["sheets"]] == [1, 2]
    assert result["sheets"][0]["size"] == list(SIZE)
    assert [b["cls"] for b in result["sheets"][0]["boxes"]] == ["window", "door"]
    assert summary["houses"]["55001"]["boxes"] == 4 and summary["sheets_total"] == 2
    assert json.loads((out / "summary.json").read_text())["sheets_total"] == 2


def test_run_skips_broken_house(tmp_path):
    """Битая картинка одного дома не роняет пакет: дом — в failed, остальные посчитаны."""
    make_house(tmp_path)
    broken = tmp_path / "55002"
    broken.mkdir()
    (broken / "facade0.jpg").write_bytes(b"not a jpeg")
    summary = owl.run(["55002", "55001"], tmp_path, tmp_path / "out", lambda: stub)
    assert summary["failed"] == ["55002"] and list(summary["houses"]) == ["55001"]
