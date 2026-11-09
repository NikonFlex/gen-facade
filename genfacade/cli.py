"""Командная строка: genfacade run <план.svg> --text …, serve, synth, buildingnet, manual, tokens,
train, eval, metrics, calibrate, baseline, guidelines, realtest, stability, review."""

import argparse
import sys
from pathlib import Path

from genfacade import config, pipeline
from genfacade.baselines import Baseline
from genfacade.datasets.synthetic import batch
from genfacade.schema import REFUSAL_TEXT, Mode, Refused, Source, Split
from genfacade.train import corpus
from genfacade.vectorizer import Backend


def run(args: argparse.Namespace) -> Path:
    """План GenPlan + текст → трасса шагов 1–6 (`generation: Конвейер из семи шагов`)."""
    cfg = config.load(*args.config)
    req = pipeline.PlanRun(plan=str(args.plan), text=args.text, mode=args.mode)
    out = args.out or pipeline.new_run_dir(cfg.viewer.paths.runs_dir, args.plan.stem)
    return pipeline.generate(req, args.plan.read_text(), out, cfg)


def synth(args: argparse.Namespace) -> Path:
    """Синтетические дома по seed подряд → примеры и опись; готовые дома пропускаются."""
    seeds = range(args.first_seed, args.first_seed + args.count)
    return batch.run(seeds, config.load(*args.config), args.overwrite)


def buildingnet(args: argparse.Namespace) -> Path:
    """Коттеджи BuildingNet частей официального разбиения → примеры и опись с отказами (gf#154,
    gf#198)."""
    from genfacade.datasets.buildingnet import build

    return build.run(config.load(*args.config), args.count, tuple(args.splits))


def markup(args: argparse.Namespace) -> Path:
    """Ручная разметка реальных коттеджей → примеры теста и опись со срезанным (gf#180)."""
    from genfacade.datasets import manual

    return manual.run(config.load(*args.config))


def tokens(args: argparse.Namespace) -> Path:
    """Собранные дома источника → номера токенов одним файлом и опись."""
    return corpus.build(args.source, config.load(*args.config))


def train(args: argparse.Namespace) -> Path:
    """Корпус источника → обученная модель шага 4, кривая потерь, ответы на val."""
    # torch — в группе [train]: без обучения пакет его не тянет.
    from genfacade.train import fit

    cfg = config.load(*args.config)
    out = args.out or pipeline.new_run_dir(cfg.train.paths.runs_dir, args.source)
    return fit.run(args.source, cfg, out)


def eval_model(args: argparse.Namespace) -> Path:
    """Модель шага 4 на val: доли разобранных и годных, статистика против эталона, повторы."""
    # torch — в группе [train]: без обучения пакет его не тянет.
    from genfacade.train import evaluate

    cfg = config.load(*args.config)
    out = args.out or pipeline.new_run_dir(cfg.train.paths.runs_dir, f"eval-{args.source}")
    return evaluate.run(args.source, cfg, out)


def metrics_table(args: argparse.Namespace) -> Path:
    """Папки листов → таблица метрик против эталона (`evaluation: Метрики одной командой`)."""
    from genfacade.metrics import table

    cfg = config.load(*args.config)
    out = args.out or pipeline.new_run_dir(cfg.train.paths.runs_dir, "metrics")
    return table.run(args.folders, args.reference, cfg, out)


def metrics_calibrate(args: argparse.Namespace) -> Path:
    """Эталон генератора против подмен на val источника: каждая метрика их различает."""
    from genfacade.metrics import calibrate

    cfg = config.load(*args.config)
    out = args.out or pipeline.new_run_dir(cfg.train.paths.runs_dir, f"calibrate-{args.source}")
    return calibrate.run(args.source, cfg, out)


def baseline(args: argparse.Namespace) -> Path:
    """Листы папки → фасады базового подхода на тех же домах (`evaluation: Базовые подходы`)."""
    from genfacade import baselines

    return baselines.run(args.name, args.source_dir, config.load(*args.config), args.out)


def realtest(args: argparse.Namespace) -> Path:
    """Таблица метрик против реального теста: модель, правило GenPlan, синтетика, подмены."""
    from genfacade.metrics import realtest

    cfg = config.load(*args.config)
    out = args.out or pipeline.new_run_dir(cfg.train.paths.runs_dir, "realtest")
    rows = realtest.Rows(dict(args.model), dict(args.sheets), dict(args.vectorized))
    return realtest.run(cfg, out, args.synthetic, rows)


def vectorize(args: argparse.Namespace) -> Path:
    """Стены реального теста → растр → готовый векторизатор → элементы (gf#17)."""
    from genfacade import vectorizer

    cfg = config.load(*args.config)
    if args.collect:
        vectorizer.collect(vectorizer.houses(cfg), cfg, args.out)
        return args.out
    return vectorizer.run(args.backend, cfg, args.out, args.limit)


def stability(args: argparse.Namespace) -> Path:
    """Папки вариантов сэмплинга реального теста → сводка с разбросом по seed (gf#257)."""
    from genfacade.metrics import stability

    return stability.run(args.root, config.load(*args.config))


def guidelines_table(args: argparse.Namespace) -> Path:
    """Свод правил фасада на домах реального теста → таблица для чтения (gf#209)."""
    from genfacade import guidelines

    return guidelines.run(config.load(*args.config), args.out)


def serve(config_dirs: list[Path], checked: Path | None = None, marked: Path | None = None) -> None:
    # uvicorn и fastapi — в группе [viewer]: без смотрелки пакет их не тянет.
    import uvicorn

    from genfacade.viewer.app import create_app

    cfg = config.load(*config_dirs)
    uvicorn.run(create_app(cfg, checked, marked), host=cfg.viewer.server.host,
                port=cfg.viewer.server.port)


def review_summary(args: argparse.Namespace) -> str:
    from genfacade.viewer import review

    return review.summary(args.folder, config.load(*args.config).viewer.review)


def _named(value: str) -> tuple[str, Path]:
    """ИМЯ=ПУТЬ → (имя, путь)."""
    name, sep, path = value.partition("=")
    if not (name and sep and path):
        raise argparse.ArgumentTypeError(f"ждали ИМЯ=ПУТЬ, а не {value!r}")
    return name, Path(path)


def _source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-s", "--source", type=Source, choices=list(Source),
                        default=Source.SYNTHETIC, help="источник домов в samples_dir")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="genfacade")
    parser.add_argument("-c", "--config", type=Path, action="append", default=[],
                        help="папка своих настроек: любые файлы из genfacade/config/; "
                             "несколько -c — следующая перекрывает предыдущую")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("run", help="план GenPlan + описание → фасады, трасса шагов 1–6")
    g.add_argument("plan", type=Path, help="SVG-план GenPlan")
    g.add_argument("-t", "--text", required=True, help="описание дома по-английски")
    g.add_argument("-m", "--mode", type=Mode, choices=list(Mode), default=Mode.WITH_OPENINGS,
                   help=f"{Mode.WITH_OPENINGS} — окна из плана (режим 2), "
                        f"{Mode.BLIND} — глухой куб (режим 1)")
    g.add_argument("-o", "--out", type=Path,
                   help="папка прогона; по умолчанию runs_dir/<время>-<имя>")
    v = sub.add_parser("serve", help="смотрелка прогонов в браузере")
    v.add_argument("--review", type=Path, help="папка genfacade realtest для слепой проверки "
                                               "листов глазами (страница /review, gf#268)")
    v.add_argument("--markup", type=Path, help="папка разметки для проверки и правки домов в "
                                               "браузере (страница /markup, gf#348); по умолчанию "
                                               "[markup] folder из config/viewer.toml")
    r = sub.add_parser("review", help="сводка слепой проверки: доля принятых листов по строкам")
    r.add_argument("folder", type=Path, help="папка genfacade realtest с review.json")
    s = sub.add_parser("synth", help="синтетические дома → примеры датасета и опись")
    s.add_argument("-n", "--count", type=int, required=True, help="сколько домов")
    s.add_argument("--first-seed", type=int, default=0, help="seed первого дома; дальше подряд")
    s.add_argument("--overwrite", action="store_true",
                   help="удалить собранные дома и собрать заново (после правки настроек или кода)")
    n = sub.add_parser("buildingnet", help="коттеджи BuildingNet → примеры датасета и опись")
    n.add_argument("-n", "--count", type=int, default=0, help="сколько домов; 0 — все")
    n.add_argument("--splits", nargs="+", type=Split, default=[Split.TEST],
                   help="части официального разбиения: train val test (по умолчанию test)")
    sub.add_parser("manual", help="ручная разметка реальных коттеджей → примеры теста и опись")
    t = sub.add_parser("tokens", help="дома источника → корпус для обучения: номера токенов")
    _source(t)
    f = sub.add_parser("train", help="корпус токенов → модель шага 4, кривая потерь, ответы")
    _source(f)
    f.add_argument("-o", "--out", type=Path,
                   help="папка обучения; по умолчанию runs_dir/<время>-<источник>")
    e = sub.add_parser("eval", help="модель шага 4 на val: годные ответы, статистика, повторы")
    _source(e)
    e.add_argument("-o", "--out", type=Path,
                   help="папка оценки; по умолчанию runs_dir/<время>-eval-<источник>")
    m = sub.add_parser("metrics", help="папки листов фасадов → таблица метрик против эталона")
    m.add_argument("folders", type=Path, nargs="+",
                   help="папки <дом>.json: строка таблицы на папку")
    m.add_argument("-r", "--reference", type=Path, required=True,
                   help="папка эталонных листов: распределение структуры и разброс признаков")
    m.add_argument("-o", "--out", type=Path,
                   help="папка metrics.json; по умолчанию runs_dir/<время>-metrics")
    k = sub.add_parser("calibrate", help="эталон генератора против подмен: таблица метрик на val")
    _source(k)
    k.add_argument("-o", "--out", type=Path,
                   help="папка подмен и таблиц; по умолчанию runs_dir/<время>-calibrate-<источник>")
    b = sub.add_parser("baseline", help="папка листов → фасады базового подхода на тех же домах")
    b.add_argument("name", choices=list(Baseline), type=Baseline, help="базовый подход")
    b.add_argument("source_dir", type=Path,
                   help="папка листов <дом>.json: берутся стены, условие режима, параметры дома")
    b.add_argument("-o", "--out", type=Path, required=True, help="папка фасадов базового подхода")
    q = sub.add_parser("realtest", help="таблица метрик против реального теста")
    q.add_argument("-n", "--synthetic", type=int, default=0, help="домов синтетики val; 0 — все")
    q.add_argument("--model", type=_named, action="append", default=[], metavar="ИМЯ=ЧЕКПОЙНТ",
                   help="строка model-ИМЯ: ответы этого чекпойнта; без --model — модель "
                        "config/models.toml, строка model")
    q.add_argument("--sheets", type=_named, action="append", default=[], metavar="ИМЯ=ПАПКА",
                   help="строка model-ИМЯ: листы <режим>/model прошлого genfacade realtest — "
                        "для модели другой записи токенов, ответившей своим кодом")
    q.add_argument("--vectorized", type=_named, action="append", default=[], metavar="ИМЯ=ПАПКА",
                   help="строка vectorizer-ИМЯ: папка `genfacade vectorize`; дома, которых в ней "
                        "нет, в строке не считаются, остальные строки — и против тех же домов")
    q.add_argument("-o", "--out", type=Path,
                   help="папка листов и таблиц; по умолчанию runs_dir/<время>-realtest")
    z = sub.add_parser("vectorize", help="стены реального теста → готовый векторизатор → элементы")
    z.add_argument("backend", choices=list(Backend), type=Backend, help="векторизатор")
    z.add_argument("-o", "--out", type=Path, required=True,
                   help="папка растров, ответов и элементов; готовые ответы не пересчитываются")
    z.add_argument("-n", "--limit", type=int, default=0, help="домов прогона; 0 — все")
    z.add_argument("--collect", action="store_true",
                   help="только собрать элементы из готовых ответов, векторизатор не запускать")
    t = sub.add_parser("stability", help="сводка реального теста по вариантам сэмплинга")
    t.add_argument("root", type=Path,
                   help="папка вариантов: <вариант>/<режим>/rows/metrics.json от realtest; "
                        "варианты — пары ключ=значение [layout] через запятую; сводка — "
                        "summary.md в ней")
    r = sub.add_parser("guidelines", help="свод правил фасада на домах реального теста → таблица")
    r.add_argument("-o", "--out", type=Path, default=Path("docs/facade-rules.md"),
                   help="файл таблицы; по умолчанию docs/facade-rules.md")
    return parser


# Команда → что делает и какие отказы, кроме Refused, печатаются строкой с причиной, а не
# трассой. Refused (план, модель) печатается своим кодом — тем же текстом, что в смотрелке.
COMMANDS = {
    "synth": (synth, {batch.BuildError: "сборка остановлена"}),
    "buildingnet": (buildingnet, {}),
    "manual": (markup, {}),
    "tokens": (tokens, {corpus.CorpusError: "корпус не собран"}),
    "train": (train, {corpus.CorpusError: "обучение не начато"}),
    "eval": (eval_model, {corpus.CorpusError: "оценка не начата"}),
    "metrics": (metrics_table, {}),
    "baseline": (baseline, {}),
    "calibrate": (metrics_calibrate, {}),
    "guidelines": (guidelines_table, {}),
    "stability": (stability, {FileNotFoundError: "сводка не начата"}),
    "realtest": (realtest, {FileNotFoundError: "таблица не начата"}),
    "vectorize": (vectorize, {RuntimeError: "векторизатор не отработал"}),
    "run": (run, {}),
    "review": (review_summary, {}),
}


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command not in COMMANDS:
        serve(args.config, getattr(args, "review", None), getattr(args, "markup", None))
        return
    command, refusals = COMMANDS[args.command]
    try:
        print(command(args))
    except Refused as e:
        sys.exit(f"{REFUSAL_TEXT[e.code]}: {e}")
    except tuple(refusals) as e:
        sys.exit(f"{refusals[type(e)]}: {e}")
