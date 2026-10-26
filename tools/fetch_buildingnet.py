"""BuildingNet v1 на машину обучения (gf#198): списки разбиения, метки компонентов и .obj/.mtl
коттеджей — выборочно из OBJ_MODELS.zip на Google Drive по HTTP Range, без 5,6 ГБ целиком.

    BUILDINGNET_DRIVE='{"obj": "…", "labels": "…", "train": "…", "val": "…", "test": "…"}' \\
        python tools/fetch_buildingnet.py <папка> [--categories RESIDENTIALhouse RESIDENTIALvilla]

Идентификаторы файлов Drive — не в репозитории: доступ к BuildingNet выдан хозяину по форме
(некоммерческое использование, не распространять, `data: BuildingNet только некоммерчески`); на
раннере они — секрет BUILDINGNET_DRIVE. Скачанное уже лежит — не качается заново.

Раскладка папки — как ждёт config/data.toml: `v1/OBJ_MODELS/<модель>.obj`,
`probe/v1/component_labels.zip`, `probe/v1/{train,val,test}_split.txt`.
"""

import argparse
import io
import json
import os
import urllib.request
import zipfile
from pathlib import Path

URL = "https://drive.usercontent.google.com/download?id={}&export=download&confirm=t"
SPLITS = ("train", "val", "test")
CHUNK = 1 << 20


class DriveFile(io.RawIOBase):
    """Файл Drive как файл с произвольным доступом: каждое чтение — запрос с Range."""

    def __init__(self, file_id: str):
        self.url, self.pos = URL.format(file_id), 0
        self.size = int(_get(self.url, "bytes=0-0").headers["Content-Range"].split("/")[1])

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, buffer) -> int:
        n = min(len(buffer), self.size - self.pos)
        if n <= 0:
            return 0
        with _get(self.url, f"bytes={self.pos}-{self.pos + n - 1}") as r:
            data = r.read()
        buffer[:len(data)] = data
        self.pos += len(data)
        return len(data)


def _get(url: str, span: str):
    # адрес — константа https (URL), схема не меняется
    request = urllib.request.Request(url, headers={"Range": span})  # noqa: S310
    return urllib.request.urlopen(request, timeout=120)  # noqa: S310


def _whole(file_id: str, target: Path) -> None:
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(URL.format(file_id), timeout=600) as r:  # noqa: S310
            target.write_bytes(r.read())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root", type=Path)
    p.add_argument("--categories", nargs="+", default=["RESIDENTIALhouse", "RESIDENTIALvilla"])
    a = p.parse_args()
    ids = json.loads(os.environ["BUILDINGNET_DRIVE"])
    probe = a.root / "probe" / "v1"
    for split in SPLITS:
        _whole(ids[split], probe / f"{split}_split.txt")
    _whole(ids["labels"], probe / "component_labels.zip")
    models = [m for split in SPLITS for m in (probe / f"{split}_split.txt").read_text().split()
              if m.startswith(tuple(a.categories))]
    out = a.root / "v1" / "OBJ_MODELS"
    out.mkdir(parents=True, exist_ok=True)
    archive = zipfile.ZipFile(io.BufferedReader(DriveFile(ids["obj"]), buffer_size=CHUNK))
    for k, model in enumerate(models, 1):
        for ext in (".obj", ".mtl"):
            if not (out / f"{model}{ext}").exists():
                (out / f"{model}{ext}").write_bytes(archive.read(f"OBJ_MODELS/{model}{ext}"))
        if k % 100 == 0:
            print(f"{k} из {len(models)}", flush=True)
    print(f"моделей {len(models)} в {out}", flush=True)


if __name__ == "__main__":
    main()
