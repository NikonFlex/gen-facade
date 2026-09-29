"""PNG-превью листа для проверки глазами."""

import shutil
import subprocess  # noqa: S404 — вызываем только rsvg-convert с путями, которые пишем сами
from pathlib import Path


def to_png(svg: Path, png: Path, width_px: int) -> bool:
    """rsvg-convert, если он есть в системе; нет — превью пропускается (False)."""
    exe = shutil.which("rsvg-convert")
    if exe is None:
        return False
    subprocess.run([exe, "-w", str(width_px), "-o", str(png), str(svg)], check=True)  # noqa: S603
    return True
