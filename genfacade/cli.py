"""Командная строка: genfacade render <дом.json>."""

import argparse
import json
import subprocess  # noqa: S404 — только git rev-parse
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from genfacade import config
from genfacade.render.preview import to_png
from genfacade.render.svg import sheet_svg
from genfacade.schema import FacadeSheet
from genfacade.unfold import unfold


def render(src: Path, out: Path, config_dir: Path | None = None) -> Path:
    """Дом из JSON → развёртка → лист: sheet.svg, sheet.json, preview.png, meta.json."""
    cfg = config.load(config_dir)
    raw = FacadeSheet.model_validate_json(src.read_text())
    sheet = unfold(raw, cfg.library.roof.thickness_m)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sheet.json").write_text(sheet.model_dump_json(indent=2))
    (out / "sheet.svg").write_text(sheet_svg(sheet, cfg))
    has_png = to_png(out / "sheet.svg", out / "preview.png", cfg.sheet.preview.width_px)
    meta = {
        "command": "render", "input": str(src),
        "date": datetime.now().isoformat(timespec="seconds"),
        "git_sha": _git_sha(), "genfacade": version("genfacade"), "preview": has_png,
        # Итоговые настройки целиком: прогон повторяется без исходной папки конфига.
        "config_dir": str(config_dir) if config_dir else None, "config": cfg.model_dump(),
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return out


def _git_sha() -> str | None:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,  # noqa: S603, S607
                             check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return res.stdout.strip()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="genfacade")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("render", help="лист фасадов из JSON дома")
    r.add_argument("src", type=Path)
    r.add_argument("-o", "--out", type=Path,
                   help="папка прогона; по умолчанию outputs/runs/<время>-<имя>")
    r.add_argument("-c", "--config", type=Path,
                   help="папка своих настроек: library.toml, sheet.toml, sheet.css — любые из них")
    args = parser.parse_args(argv)
    out = args.out or Path("outputs/runs") / f"{datetime.now():%Y%m%d-%H%M%S}-{args.src.stem}"
    print(render(args.src, out, args.config))
