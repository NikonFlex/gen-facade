"""Командная строка: genfacade render <дом.json>, genfacade serve."""

import argparse
from pathlib import Path

from genfacade import config, pipeline
from genfacade.schema import FacadeSheet


def render(src: Path, out: Path | None, config_dir: Path | None) -> Path:
    """Дом из JSON → трасса прогона: шаги, лист, PNG, meta.json."""
    cfg = config.load(config_dir)
    house = FacadeSheet.model_validate_json(src.read_text())
    out = out or pipeline.new_run_dir(cfg.viewer.paths.runs_dir, src.stem)
    return pipeline.run(house, out, cfg, source=str(src))


def serve(config_dir: Path | None) -> None:
    # uvicorn и fastapi — в группе [viewer]: без смотрелки пакет их не тянет.
    import uvicorn

    from genfacade.viewer.app import create_app

    cfg = config.load(config_dir)
    uvicorn.run(create_app(cfg), host=cfg.viewer.server.host, port=cfg.viewer.server.port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="genfacade")
    parser.add_argument("-c", "--config", type=Path,
                        help="папка своих настроек: любые файлы из genfacade/config/")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("render", help="лист фасадов из JSON дома")
    r.add_argument("src", type=Path)
    r.add_argument("-o", "--out", type=Path,
                   help="папка прогона; по умолчанию runs_dir/<время>-<имя>")
    sub.add_parser("serve", help="смотрелка прогонов в браузере")
    args = parser.parse_args(argv)
    if args.command == "render":
        print(render(args.src, args.out, args.config))
    else:
        serve(args.config)
