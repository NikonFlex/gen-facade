"""Оценка модели шага 4 на val (gf#108): `genfacade eval` → таблица в консоль и `eval.json`.

Модель отвечает на условие каждой последовательности val (дом × режим) с первой попытки — без
повторов конвейера. Ответ разбирается и проверяется валидатором до и после привязки (шаг 5).
Те же числа считаются для эталона — ответа генератора синтетики, «правила» — и для необученной
модели того же размера: между ними и видно, чему модель научилась.

Проверки:
- разобрано; без ошибок валидатора до и после привязки; проёмы плана на месте до привязки;
- статистика стен — окон на стену, глухие стены, размеры окон, зоны — против эталона тех же домов;
- дословные повторы ответов train;
- реакция на условие: число окон на стене против эталона того же дома и против длины стены.

Ответы после привязки (шаг 5) выгружаются листами для `genfacade metrics` (gf#16):

    <out>/sheets/<кто>/<режим>/<дом>.json   — лист; неразобранный ответ — {"error": "…"}
"""

import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import NamedTuple

import numpy
import torch

from genfacade.config import Config
from genfacade.datasets import store
from genfacade.models import layout
from genfacade.pipeline import git_sha
from genfacade.schema import (
    Device,
    ElementClass,
    FacadeSheet,
    Mode,
    Rule,
    Source,
    Split,
    Violation,
)
from genfacade.snap import snap
from genfacade.train import constraints, corpus, fit, sampling, tokens
from genfacade.train.gpt import GPT
from genfacade.train.tokens import TokenError
from genfacade.validate import errors, validate

EVAL = "eval.json"
SHEETS = "sheets"
MODEL, CONSTRAINED, REFERENCE, UNTRAINED = "model", "constrained", "reference", "untrained"
WHO = (MODEL, CONSTRAINED, REFERENCE, UNTRAINED)  # строки таблицы; constrained — с запретом gf#132


class Case(NamedTuple):
    """Последовательность val: условие, ответ генератора и стены дома до ответа."""

    sample: str
    mode: Mode
    prompt: list[int]     # условие до `<answer>` включительно
    reference: list[int]  # ответ генератора от `<answer>` до `<end>`
    bare: FacadeSheet


class Judged(NamedTuple):
    """Ответ после разбора и проверки: стены (None — не разобран) и ошибки валидатора."""

    sheet: FacadeSheet | None
    error: str | None
    raw: list[Violation]      # ошибки до привязки
    snapped: list[Violation]  # ошибки после привязки — как в конвейере


def cases(part: fit.Sequences, rows: list[int], source: Source, cfg: Config) -> list[Case]:
    root = cfg.data.paths.samples_dir
    return [Case(part.sample[i], part.mode[i], part.ids[i][:part.answer_at[i] + 1].tolist(),
                 part.ids[i][part.answer_at[i]:].tolist(),
                 _as_input(store.read(root, source, part.sample[i]).sheet, part.mode[i]))
            for i in rows]


def _as_input(sheet: FacadeSheet, mode: Mode) -> FacadeSheet:
    """Стены дома такими, какими их видит модель в этом режиме: без элементов, а на сторонах —
    только проёмы условия."""
    return tokens.bare(tokens.given_sides(sheet, mode))


def judge(ids: list[int], case: Case, words: list[str], cfg: Config) -> Judged:
    try:
        sheet = tokens.decode([words[i] for i in ids], case.bare, cfg)
    except TokenError as e:
        return Judged(None, str(e), [], [])
    return Judged(sheet, None, errors(validate(sheet, cfg.checks)),
                  errors(validate(snap(sheet, cfg.checks), cfg.checks)))


def summary(judged: list[Judged], group: list[Case]) -> dict:
    """Доли от всех ответов группы; проёмы плана на месте — от всех проёмов планов группы,
    у неразобранного ответа все его проёмы пропали."""
    n = len(judged)
    parsed = [j for j in judged if j.sheet is not None]
    openings = [sum(len(f.side.openings) for f in c.bare.facades) for c in group]
    in_place = sum(k - sum(v.rule is Rule.PLAN_OPENING for v in j.raw)
                   for j, k in zip(judged, openings, strict=True) if j.sheet is not None)
    return {
        "count": n,
        "parsed": _share(len(parsed), n),
        "valid_raw": _share(sum(not j.raw for j in parsed), n),
        "valid_snapped": _share(sum(not j.snapped for j in parsed), n),
        "plan_openings_in_place": _share(in_place, sum(openings)),
        "raw_errors": dict(Counter(str(v.rule) for j in parsed for v in j.raw).most_common()),
        "parse_errors": dict(Counter(_kind(j.error) for j in judged if j.error).most_common()),
    }


class Probe:
    """Датчик по эпохам обучения (gf#148): ответы модели с первой попытки, без запрета, на первые
    `probe.count` последовательностей глухого режима val — разобрано, годных до привязки,
    ошибки валидатора по правилам. Свой генератор случайных чисел: обучение идёт так же, как
    без датчика."""

    def __init__(self, data: fit.Corpus, source: Source, cfg: Config):
        part = data.parts[Split.VAL]
        rows = [i for i, m in enumerate(part.mode) if m is Mode.BLIND][:cfg.train.probe.count]
        self.group, self.words, self.cfg = cases(part, rows, source, cfg), data.words, cfg

    def measure(self, sampler: sampling.Sampler) -> dict:
        opts = self.cfg.train.sample
        devices = [sampler.device] if sampler.device.type == Device.CUDA else []
        with torch.random.fork_rng(devices=devices):
            torch.manual_seed(self.cfg.train.fit.seed)
            answers = sampling.answer_all(sampler, [sampling.Prompt(c.prompt) for c in self.group],
                                          opts, opts.batch)
        judged = [judge(a, c, self.words, self.cfg)
                  for a, c in zip(answers, self.group, strict=True)]
        return summary(judged, self.group)


def _kind(error: str) -> str:
    """Причина брака разбора без места и чисел: какой токен пришёл вместо ожидаемого."""
    return re.sub(r"\d+", "…", error.split(": ", 1)[-1])


def _share(k: float, n: int) -> float | None:
    return round(k / n, 4) if n else None


def stats(sheets: list[FacadeSheet]) -> dict:
    """Статистика стен: окон на стену, доля глухих, средние размеры окон, зон и элементов."""
    walls = [f for s in sheets for f in s.facades]
    windows = [e for f in walls for e in f.elements if e.cls is ElementClass.WINDOW]
    if not walls:
        return {}
    return {
        "walls": len(walls),
        "windows_per_wall": round(len(windows) / len(walls), 3),
        "blind_walls": _share(sum(not _windows(f) for f in walls), len(walls)),
        "window_w_m": round(mean(e.w_m for e in windows), 3) if windows else None,
        "window_h_m": round(mean(e.h_m for e in windows), 3) if windows else None,
        "zones_per_wall": round(mean(len(f.zones) for f in walls), 3),
        "elements_per_wall": round(mean(len(f.elements) for f in walls), 3),
    }


def _windows(f) -> int:
    return sum(e.cls is ElementClass.WINDOW for e in f.elements)


def reaction(model: list[FacadeSheet], reference: list[FacadeSheet]) -> dict:
    """Корреляция числа окон на стене: с эталоном того же дома и с длиной стены. Модель, которая
    не слушает условие, даст около нуля там, где эталон даёт много."""
    pairs = [(f, g) for m, r in zip(model, reference, strict=True)
             for f, g in zip(m.facades, r.facades, strict=True)]
    if len(pairs) < 3:
        return {}
    ours = [_windows(f) for f, _ in pairs]
    theirs = [_windows(g) for _, g in pairs]
    length = [f.side.length_m for f, _ in pairs]
    return {"windows_vs_reference": _corr(ours, theirs),
            "windows_vs_length": _corr(ours, length),
            "reference_windows_vs_length": _corr(theirs, length)}


def _corr(a: list[float], b: list[float]) -> float | None:
    if numpy.std(a) == 0 or numpy.std(b) == 0:
        return None
    return round(float(numpy.corrcoef(a, b)[0, 1]), 3)


def copies(answers: list[list[int]], train: set[tuple[int, ...]]) -> float | None:
    """Доля ответов, дословно совпавших с каким-нибудь ответом train."""
    return _share(sum(tuple(a) in train for a in answers), len(answers))


class Evaluation:
    """Последовательности val, словарь и ответы train — общее для всех, кого оцениваем."""

    def __init__(self, data: fit.Corpus, group: list[Case], cfg: Config):
        self.group, self.words, self.cfg = group, data.words, cfg
        part = data.parts[Split.TRAIN]
        self.train = {tuple(part.ids[i][part.answer_at[i]:].tolist())
                      for i in range(len(part.ids))}

    def report(self, answers: list[list[int]]) -> tuple[dict, list[Judged]]:
        """Сводка по всем и по режимам на первых len(answers) последовательностях."""
        group = self.group[:len(answers)]
        judged = [judge(a, c, self.words, self.cfg) for a, c in zip(answers, group, strict=True)]
        by_mode = {m: summary([j for j, c in zip(judged, group, strict=True) if c.mode is m],
                              [c for c in group if c.mode is m]) for m in Mode}
        return {"all": summary(judged, group), "by_mode": by_mode,
                "copies_of_train": copies(answers, self.train)}, judged


def run(source: Source, cfg: Config, out: Path) -> Path:
    """Модель шага 4 из config/models.toml на val; вернуть путь к eval.json."""
    data = fit.load(source, cfg)
    trained = layout.load(cfg.models.layout)
    if trained.words != data.words:
        raise corpus.CorpusError("словарь модели не совпадает со словарём корпуса: переобучить")
    rows = _chosen(len(data.parts[Split.VAL].ids), cfg)
    ev = Evaluation(data, cases(data.parts[Split.VAL], rows, source, cfg), cfg)
    result, seconds = _reports(ev, trained.sampler, cfg)
    report = {who: r for who, (r, _) in result.items()}
    for who, (_, judged) in result.items():
        dump(judged, ev.group, out / SHEETS / who, cfg)
    report["compare"] = _compare({w: result[w][1] for w in (MODEL, CONSTRAINED, REFERENCE)},
                                 ev.group)
    report["seconds_per_answer"] = round(seconds / len(ev.group), 3)
    report["settings"] = _settings(trained.sampler, cfg)
    out.mkdir(parents=True, exist_ok=True)
    (out / EVAL).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(table(report))
    return out / EVAL


def dump(judged: list[Judged], group: list[Case], out: Path, cfg: Config) -> None:
    """Листы ответов после привязки, как их отдаёт конвейер, — по папке на режим."""
    for j, c in zip(judged, group, strict=False):
        folder = out / c.mode
        folder.mkdir(parents=True, exist_ok=True)
        text = (json.dumps({"error": j.error}, ensure_ascii=False) if j.sheet is None
                else snap(j.sheet, cfg.checks).model_dump_json())
        (folder / f"{c.sample}.json").write_text(text)


def _reports(ev: Evaluation, sampler: sampling.Sampler, cfg: Config) -> tuple[dict, float]:
    """Модель без запрета и с ним, эталон генератора, необученная модель; время без запрета."""
    vocab = constraints.Vocab(ev.words)
    free = [sampling.Prompt(c.prompt) for c in ev.group]
    guarded = [sampling.Prompt(c.prompt, constraints.guard(c.bare, c.mode, vocab, cfg))
               for c in ev.group]
    answers, seconds = _answers(sampler, free, cfg)
    blank = _answers(_untrained(sampler), free[:cfg.train.eval.untrained], cfg)[0]
    return {MODEL: ev.report(answers),
            CONSTRAINED: ev.report(_answers(sampler, guarded, cfg)[0]),
            REFERENCE: ev.report([c.reference for c in ev.group]),
            UNTRAINED: ev.report(blank)}, seconds


def _settings(sampler: sampling.Sampler, cfg: Config) -> dict:
    return {"checkpoint": str(cfg.models.layout.checkpoint), "eval": cfg.train.eval.model_dump(),
            "sampling": cfg.models.layout.model_dump(mode="json"), "device": str(sampler.device),
            "date": datetime.now().isoformat(timespec="seconds"), "git_sha": git_sha()}


def _chosen(n: int, cfg: Config) -> list[int]:
    count = cfg.train.eval.count
    if not count or count >= n:
        return list(range(n))
    rng = numpy.random.default_rng(cfg.models.layout.seed)
    return sorted(rng.permutation(n)[:count].tolist())


def _answers(sampler: sampling.Sampler, prompts: list[sampling.Prompt],
             cfg: Config) -> tuple[list, float]:
    torch.manual_seed(cfg.models.layout.seed)
    start = time.perf_counter()
    answers = sampling.answer_all(sampler, prompts, cfg.models.layout, cfg.train.eval.batch)
    return answers, time.perf_counter() - start


def _untrained(trained: sampling.Sampler) -> sampling.Sampler:
    """Та же архитектура и размер, веса — случайные: нижняя граница."""
    model = GPT(trained.model.config).to(trained.device)
    return sampling.Sampler(model, trained.end, trained.bf16)


def _compare(judged: dict[str, list[Judged]], group: list[Case]) -> dict:
    """Статистика и реакция на условие модели без запрета и с ним против эталона — на домах,
    где ответ модели разобран."""
    out: dict = {}
    for m in Mode:
        out[m] = {}
        for who in (MODEL, CONSTRAINED):
            pairs = [(a.sheet, b.sheet)
                     for a, b, c in zip(judged[who], judged[REFERENCE], group, strict=True)
                     if c.mode is m and a.sheet is not None and b.sheet is not None]
            ours, theirs = [a for a, _ in pairs], [b for _, b in pairs]
            out[m][who] = {"stats": stats(ours), "reaction": reaction(ours, theirs)}
            out[m][REFERENCE] = stats(theirs)
    return out


def table(report: dict) -> str:
    """Главное из eval.json строками для консоли."""
    keys = ["parsed", "valid_raw", "valid_snapped", "plan_openings_in_place"]
    lines = ["кто / режим".ljust(26) + "".join(k.rjust(24) for k in keys)]
    for who in WHO:
        for mode, s in report[who]["by_mode"].items():
            lines.append(f"{who} / {mode}".ljust(26) + "".join(str(s[k]).rjust(24) for k in keys))
    for who in WHO:
        lines.append(f"{who}: повторов train {report[who]['copies_of_train']}, "
                     f"ошибки до привязки {report[who]['all']['raw_errors']}")
    for mode, c in report["compare"].items():
        lines.append(f"{mode}: эталон {c[REFERENCE]}")
        for who in (MODEL, CONSTRAINED):
            lines.append(f"{mode}: {who} {c[who]['stats']}, реакция {c[who]['reaction']}")
    lines.append(f"секунд на ответ: {report['seconds_per_answer']}")
    return "\n".join(lines)
