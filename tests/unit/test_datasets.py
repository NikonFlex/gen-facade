"""Примеры датасета на диске: Sample, файл на дом, опись источника (specs/data.md)."""

import json

import pytest
from pydantic import ValidationError

from genfacade.datasets import store
from genfacade.schema import ElementClass, Sample, Source, Split


def test_sample_survives_disk(sample, tmp_path):
    out = store.write(sample, tmp_path)
    assert out == tmp_path / "synthetic" / "simple_house.json"
    assert store.read(tmp_path, Source.SYNTHETIC, sample.id) == sample


@pytest.mark.parametrize("bad_id", ["../escape", "_manifest", "a/b", ""])
def test_id_is_safe_file_name(sample, bad_id):
    with pytest.raises(ValidationError, match="id"):
        Sample.model_validate({**sample.model_dump(), "id": bad_id})


def test_facade_for_every_plan_side(sample):
    sheet = sample.sheet.model_copy(update={"facades": sample.sheet.facades[:-1]})
    with pytest.raises(ValidationError, match="сторон плана 4, а фасадов 3"):
        Sample.model_validate({**sample.model_dump(), "sheet": sheet.model_dump()})


def test_sample_without_plan(sample):
    """Источник без плана (CMP): фасады есть, плана нет."""
    assert Sample.model_validate({**sample.model_dump(), "plan": None}).plan is None


def test_manifest_counts_samples_walls_and_classes(sample, tmp_path):
    for name, split in (("b", Split.TEST), ("a", Split.TRAIN), ("c", Split.TRAIN)):
        store.write(sample.model_copy(update={"id": name, "split": split}), tmp_path)
    saved = json.loads(store.write_manifest(tmp_path, Source.SYNTHETIC).read_text())
    windows = sum(e.cls is ElementClass.WINDOW for f in sample.sheet.facades for e in f.elements)
    assert store.ids(tmp_path, Source.SYNTHETIC) == ["a", "b", "c"]  # опись — не пример
    assert (saved["samples"], saved["walls"]) == (3, 12)
    assert saved["splits"] == {"test": 1, "train": 2}
    assert windows > 0 and saved["elements"]["window"] == 3 * windows


def test_source_without_samples_is_empty(tmp_path):
    assert store.ids(tmp_path, Source.CMP) == []
