"""Командная строка: genfacade run <план.svg> --text …, genfacade serve, genfacade synth."""

import argparse
import sys
from pathlib import Path

from genfacade import config, pipeline
from genfacade.datasets.synthetic import batch
from genfacade.models.stub import ModelError
from genfacade.plan.genplan_svg import PlanError
from genfacade.schema import Mode


def run(args: argparse.Namespace) -> Path:
    """План GenPlan + текст → трасса шагов 1–6 (generation.md, п. 1)."""
    cfg = config.load(args.config)
    req = pipeline.PlanRun(plan=str(args.plan), text=args.text, mode=args.mode)
    out = args.out or pipeline.new_run_dir(cfg.viewer.paths.runs_dir, args.plan.stem)
    return pipeline.generate(req, args.plan.read_text(), out, cfg)


def synth(args: argparse.Namespace) -> Path:
    """Синтетические дома по seed подряд → примеры и опись; готовые дома пропускаются."""
    seeds = range(args.first_seed, args.first_seed + args.count)
    return batch.run(seeds, config.load(args.config), args.overwrite)


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
    g = sub.add_parser("run", help="план GenPlan + описание → фасады, трасса шагов 1–6")
    g.add_argument("plan", type=Path, help="SVG-план GenPlan")
    g.add_argument("-t", "--text", required=True, help="описание дома по-английски")
    g.add_argument("-m", "--mode", type=Mode, choices=list(Mode), default=Mode.WITH_OPENINGS,
                   help=f"{Mode.WITH_OPENINGS} — окна из плана (режим 2), "
                        f"{Mode.BLIND} — глухой куб (режим 1)")
    g.add_argument("-o", "--out", type=Path,
                   help="папка прогона; по умолчанию runs_dir/<время>-<имя>")
    sub.add_parser("serve", help="смотрелка прогонов в браузере")
    s = sub.add_parser("synth", help="синтетические дома → примеры датасета и опись")
    s.add_argument("-n", "--count", type=int, required=True, help="сколько домов")
    s.add_argument("--first-seed", type=int, default=0, help="seed первого дома; дальше подряд")
    s.add_argument("--overwrite", action="store_true",
                   help="удалить собранные дома и собрать заново (после правки настроек или кода)")
    args = parser.parse_args(argv)
    if args.command == "synth":
        try:
            print(synth(args))
        except batch.BuildError as e:
            sys.exit(f"сборка остановлена: {e}")
    elif args.command == "run":
        try:
            print(run(args))
        except PlanError as e:
            sys.exit(f"план отклонён: {e}")
        except ModelError as e:
            sys.exit(f"модель не ответила: {e}")
    else:
        serve(args.config)
