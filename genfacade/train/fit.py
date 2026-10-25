"""Обучение модели шага 4 одной командой (gf#106): корпус токенов → чекпойнт, кривая потерь,
ответы модели на условия из val и доля тех, что разбирает `tokens.decode`.

    <папка>/model.pt      веса и размеры модели; model-e<N>.pt — после эпохи N (`fit.save_every`)
    <папка>/model.json    настройки, корпус, словарь, история по эпохам, итог сэмплирования
    <папка>/loss.png      кривая потерь train и val по эпохам; loss.json — те же числа
    <папка>/samples.json  ответы модели: дом, режим, токены, разобран ли и почему нет

Loss — только на ответе: условие и паддинг помечены `gpt.IGNORE`. Последовательности разной
длины дополняются справа токеном `<end>`: внимание причинное, хвост на ответ не влияет.
"""

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import numpy
import torch

from genfacade.config import Config, Fit
from genfacade.datasets import store
from genfacade.pipeline import git_sha
from genfacade.schema import Device, Mode, Source, Split
from genfacade.train import corpus, plot, sampling, tokens
from genfacade.train.gpt import IGNORE
from genfacade.train.tokens import Mark, TokenError

MODEL, SETTINGS, SAMPLES = "model.pt", "model.json", "samples.json"


class Sequences(NamedTuple):
    """Последовательности одной части корпуса: условие и ответ вместе."""

    ids: list[numpy.ndarray]
    answer_at: list[int]  # место `<answer>`: до него включительно — условие
    sample: list[str]
    mode: list[Mode]


class Corpus(NamedTuple):
    parts: dict[Split, Sequences]
    words: list[str]
    longest: int


def load(source: Source, cfg: Config) -> Corpus:
    """Корпус с диска (`genfacade tokens`); словарь должен совпасть с нынешней записью."""
    folder = cfg.data.paths.samples_dir / source
    if not (folder / corpus.ARRAYS).exists():
        raise corpus.CorpusError(f"нет {folder / corpus.ARRAYS}: сначала genfacade tokens")
    # массивы — в память один раз: обращение к ключу npz каждый раз распаковывает массив заново
    with numpy.load(folder / corpus.ARRAYS) as npz:
        data = {key: npz[key] for key in npz.files}
    words = [str(w) for w in data["vocabulary"]]
    if words != tokens.vocabulary(cfg):
        raise corpus.CorpusError("словарь корпуса не совпадает с нынешним: genfacade tokens")
    answer = words.index(Mark.ANSWER)
    starts = [0, *data["ends"][:-1]]
    seqs = [data["ids"][a:b].astype(numpy.int64) for a, b in zip(starts, data["ends"], strict=True)]
    parts = {}
    for split in corpus.SPLITS:
        rows = [i for i in range(len(seqs)) if corpus.SPLITS[data["split"][i]] is split]
        parts[split] = Sequences([seqs[i] for i in rows],
                                 [int(numpy.argmax(seqs[i] == answer)) for i in rows],
                                 [str(data["sample"][i]) for i in rows],
                                 [corpus.MODES[data["mode"][i]] for i in rows])
    return Corpus(parts, words, max(len(s) for s in seqs))


def mixed(source: Source, cfg: Config) -> Corpus:
    """Корпус источника и подмешанные к его train последовательности других (`[fit.mix]`),
    случайные с seed обучения; val и test — только источника."""
    data, rng = load(source, cfg), numpy.random.default_rng(cfg.train.fit.seed)
    parts, longest = dict(data.parts), data.longest
    for extra, count in cfg.train.fit.mix.items():
        more = load(extra, cfg)
        add, own = more.parts[Split.TRAIN], parts[Split.TRAIN]
        rows = sorted(rng.choice(len(add.ids), min(count, len(add.ids)), replace=False).tolist())
        parts[Split.TRAIN] = Sequences(*(mine + [theirs[i] for i in rows]
                                         for mine, theirs in zip(own, add, strict=True)))
        longest = max(longest, *(len(add.ids[i]) for i in rows))
    if cfg.train.fit.skip_longer:
        parts = {split: _within(part, cfg.train.model.block) for split, part in parts.items()}
        longest = min(longest, cfg.train.model.block)
    return Corpus(parts, data.words, longest)


def _within(part: Sequences, block: int) -> Sequences:
    """Последовательности не длиннее окна модели."""
    rows = [i for i, ids in enumerate(part.ids) if len(ids) <= block]
    return Sequences(*([column[i] for i in rows] for column in part))


def batch(part: Sequences, rows: list[int], pad: int) -> tuple[torch.Tensor, torch.Tensor]:
    """Вход и метки: метка позиции j — токен j+1; условие и паддинг в loss не идут."""
    width = max(len(part.ids[i]) for i in rows) - 1
    x = torch.full((len(rows), width), pad, dtype=torch.long)
    y = torch.full((len(rows), width), IGNORE, dtype=torch.long)
    for k, i in enumerate(rows):
        seq = torch.from_numpy(part.ids[i])
        x[k, :len(seq) - 1] = seq[:-1]
        y[k, :len(seq) - 1] = seq[1:]
        y[k, :part.answer_at[i]] = IGNORE  # первый токен ответа предсказывается на `<answer>`
    return x, y


def learning_rate(step: int, total: int, fit: Fit) -> float:
    """Линейный разгон, потом косинус до min_lr — как в nanoGPT."""
    if step < fit.warmup_steps:
        return fit.lr * (step + 1) / fit.warmup_steps
    progress = min(1.0, (step - fit.warmup_steps) / max(1, total - fit.warmup_steps))
    return fit.min_lr + 0.5 * (1 + math.cos(math.pi * progress)) * (fit.lr - fit.min_lr)


class Trainer:
    """Модель, оптимизатор и счётчик шагов одного обучения."""

    def __init__(self, data: Corpus, cfg: Config):
        fit, self.fit, self.data = cfg.train.fit, cfg.train.fit, data
        if data.longest > cfg.train.model.block:
            raise corpus.CorpusError(f"окно {cfg.train.model.block} короче самой длинной "
                                     f"последовательности корпуса ({data.longest})")
        self.device = sampling.device(fit.device)
        self.cuda = self.device.type == Device.CUDA
        self.model = sampling.build_model(cfg.train.model, len(data.words))
        if fit.init is not None:
            _start_from(self.model, fit.init, data.words)
        self.model.to(self.device)
        self.opt = self.model.configure_optimizers(fit.weight_decay, fit.lr, fit.betas, self.cuda)
        self.forward = torch.compile(self.model) if fit.compile else self.model
        self.pad = data.words.index(Mark.END)
        self.sampler = sampling.Sampler(self.model, self.pad, fit.bf16)
        self.step = 0
        self.total = fit.epochs * math.ceil(len(data.parts[Split.TRAIN].ids) / fit.batch)

    def loss(self, part: Sequences, rows: list[int]) -> tuple[torch.Tensor, int]:
        """Средний loss на токенах ответа и их число."""
        x, y = (t.to(self.device) for t in batch(part, rows, self.pad))
        with self.sampler.autocast():
            _, loss = self.forward(x, y)
        return loss, int((y != IGNORE).sum())

    def epoch(self, rng: numpy.random.Generator) -> float:
        self.model.train()
        part = self.data.parts[Split.TRAIN]
        order = rng.permutation(len(part.ids)).tolist()
        total = count = 0
        for start in range(0, len(order), self.fit.batch):
            for group in self.opt.param_groups:
                group["lr"] = learning_rate(self.step, self.total, self.fit)
            loss, n = self.loss(part, order[start:start + self.fit.batch])
            self.opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.fit.grad_clip)
            self.opt.step()
            self.step += 1
            total, count = total + loss.item() * n, count + n
        return total / count

    @torch.no_grad()
    def evaluate(self, split: Split) -> float:
        self.model.eval()
        part = self.data.parts[split]
        total = count = 0
        for start in range(0, len(part.ids), self.fit.batch):
            loss, n = self.loss(part, list(range(start, min(start + self.fit.batch,
                                                            len(part.ids)))))
            total, count = total + loss.item() * n, count + n
        return total / count


def _start_from(model: torch.nn.Module, path: Path, words: list[str]) -> None:
    """Дообучение: веса чекпойнта; другой словарь — другая запись токенов, веса не подходят."""
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if list(checkpoint["vocabulary"]) != words:
        raise corpus.CorpusError(f"словарь {path} не совпадает с корпусом: дообучать нельзя")
    model.load_state_dict(checkpoint["model"])


def run(source: Source, cfg: Config, out: Path) -> Path:
    """Обучить, сохранить, сэмплировать; вернуть путь к model.json."""
    fit = cfg.train.fit
    torch.manual_seed(fit.seed)
    rng = numpy.random.default_rng(fit.seed)
    data = mixed(source, cfg)
    trainer = Trainer(data, cfg)
    out.mkdir(parents=True, exist_ok=True)
    probe = _probe(data, source, cfg)
    history = []
    for epoch in range(1, fit.epochs + 1):
        history.append(_timed_epoch(trainer, rng) | {"epoch": epoch})
        if probe and (epoch % cfg.train.probe.every == 0 or epoch == fit.epochs):
            history[-1]["probe"] = probe.measure(trainer.sampler)
        print(json.dumps(history[-1]), flush=True)
        if fit.save_every and epoch % fit.save_every == 0 and epoch < fit.epochs:
            _save(trainer, data, cfg, out / f"model-e{epoch}.pt")
    _save(trainer, data, cfg, out / MODEL)
    plot.losses(history, out)
    samples = sample(trainer, source, cfg, rng)
    (out / SAMPLES).write_text(json.dumps(samples, ensure_ascii=False, indent=1))
    summary = {k: v for k, v in samples.items() if k != "rows"}
    counts = {split.value: len(part.ids) for split, part in data.parts.items()}
    return _settings(trainer, cfg, {"source": source, "sequences": counts, "history": history,
                                    "samples": summary}, out)


def _save(trainer: Trainer, data: Corpus, cfg: Config, path: Path) -> None:
    """Веса, размеры и словарь — то, что читает `models.layout.load`."""
    torch.save({"model": trainer.model.state_dict(), "size": cfg.train.model.model_dump(),
                "vocabulary": data.words}, path)


def _probe(data: Corpus, source: Source, cfg: Config):
    """Датчик по эпохам (`evaluate.Probe`); every = 0 — выключен."""
    if not cfg.train.probe.every:
        return None
    # evaluate сам импортирует fit: здесь — только при обучении, а не при загрузке модуля
    from genfacade.train import evaluate

    return evaluate.Probe(data, source, cfg)


def _timed_epoch(trainer: Trainer, rng: numpy.random.Generator) -> dict:
    if trainer.cuda:
        torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    train_loss = trainer.epoch(rng)
    seconds = time.perf_counter() - start
    peak = torch.cuda.max_memory_allocated() if trainer.cuda else 0
    return {"train": round(train_loss, 5), "val": round(trainer.evaluate(Split.VAL), 5),
            "seconds": round(seconds, 1), "peak_memory_gib": round(peak / 2**30, 2)}


# ——— сэмплирование ———

def sample(trainer: Trainer, source: Source, cfg: Config, rng: numpy.random.Generator) -> dict:
    """Ответы модели на условия случайных последовательностей val; разбирает ли их decode."""
    part = trainer.data.parts[Split.VAL]
    chosen = sorted(rng.permutation(len(part.ids))[:cfg.train.sample.count].tolist())
    prompts = [sampling.Prompt(part.ids[i][:part.answer_at[i] + 1].tolist()) for i in chosen]
    answers = dict(zip(chosen, sampling.answer_all(trainer.sampler, prompts, cfg.train.sample,
                                                   cfg.train.sample.batch), strict=True))
    root = cfg.data.paths.samples_dir
    rows = []
    for i in chosen:
        walls = tokens.bare(store.read(root, source, part.sample[i]).sheet)
        words = [trainer.data.words[t] for t in answers[i]]
        rows.append({"sample": part.sample[i], "mode": part.mode[i], "tokens": words,
                     "error": _decode_error(words, walls, cfg)})
    return {"count": len(rows), "parsed": sum(r["error"] is None for r in rows),
            "by_mode": {m: _share([r for r in rows if r["mode"] is m]) for m in Mode},
            "rows": rows}


def _decode_error(words: list[str], walls, cfg: Config) -> str | None:
    try:
        tokens.decode(words, walls, cfg)
    except TokenError as e:
        return str(e)
    return None


def _share(rows: list[dict]) -> dict:
    return {"count": len(rows), "parsed": sum(r["error"] is None for r in rows)}


def _settings(trainer: Trainer, cfg: Config, result: dict, out: Path) -> Path:
    """model.json: с чем и на чём учили и что вышло (result: источник, история, сэмплы)."""
    manifest = cfg.data.paths.samples_dir / result["source"] / corpus.MANIFEST
    gpu = torch.cuda.get_device_name() if trainer.cuda else None
    settings = {
        "train": cfg.train.model_dump(mode="json"),
        "tokens": cfg.tokens.model_dump(mode="json"),
        "corpus": json.loads(manifest.read_text()) if manifest.exists() else None,
        "parameters": trainer.model.get_num_params(),
        "device": str(trainer.device), "gpu": gpu, "torch": torch.__version__,
        **result,
        "date": datetime.now().isoformat(timespec="seconds"),
        "git_sha": git_sha(),
    }
    path = out / SETTINGS
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2))
    return path
