"""Модель шага 4 в конвейере (gf#107): брак — заново с новым seed, предел попыток — отказ.

Модель подменяется: тесты не учат и не грузят чекпойнт, поэтому идут и без torch.
"""

import json

import pytest
from simple_house import SIMPLE

from genfacade import pipeline
from genfacade.datasets import store
from genfacade.metrics import realism
from genfacade.models import stub
from genfacade.models.stub import ModelError
from genfacade.plan.preprocess import preprocess
from genfacade.schema import ElementClass, Mode
from genfacade.train import tokens
from genfacade.train.tokens import Answer, TokenError

MODE = Mode.WITH_OPENINGS


def _good(bare):
    return stub.layout_all(bare, stub.LayoutContext(bare.spec, MODE, ""))


def _without_door(bare):
    """Ответ, который разобран, но не годен: вход плана пропал — ошибка валидатора."""
    sheet = _good(bare)
    front = sheet.facades[0]
    kept = [e for e in front.elements if e.cls is not ElementClass.DOOR]
    return sheet.model_copy(update={"facades": [front.model_copy(update={"elements": kept}),
                                                *sheet.facades[1:]]})


class Fake:
    """Подмена обученной модели: ответы по очереди — функция от стен или исключение; на
    досэмплирование стены — тоже следующий из очереди, с пометкой, какая стена."""

    def __init__(self, *answers):
        self.queue, self.seeds, self.walls = list(answers), [], []

    def prompt(self, bare, mode, cfg):
        return mode

    def answer(self, prompt, bare, seed, cfg):
        self.seeds.append(seed)
        answer = self.queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Answer([], answer(bare))

    def answers(self, prompt, bare, seed, cfg, n):
        """Пачка из n — следующие n ответов очереди; неразобранный — исключение на его месте."""
        return [self._next(bare, seed) for _ in range(n)]

    def _next(self, bare, seed):
        try:
            return self.answer(None, bare, seed, None)
        except TokenError as e:
            return e

    def redo(self, prompt, bare, old, wall, seed, cfg):
        self.walls.append(wall)
        return self.answer(prompt, bare, seed, cfg)


@pytest.fixture
def run(monkeypatch, cfg, tmp_path):
    """Прогон простого дома с подменённой моделью; вернуть meta.json и модель."""
    def go(model, settings=cfg):
        monkeypatch.setattr(pipeline, "trained_model", lambda settings: model)
        req = pipeline.PlanRun(plan=str(SIMPLE), text="", mode=MODE)
        out = pipeline.generate(req, SIMPLE.read_text(), tmp_path / "run", settings)
        return json.loads((out / pipeline.META).read_text()), out

    return go


def test_bad_answers_are_regenerated_with_next_seed(run, cfg):
    model = Fake(TokenError("оборвался"), _without_door, _good)
    meta, out = run(model)
    seed = cfg.models.layout.seed
    assert model.seeds == [seed, seed + 1, seed + 2]
    errors = [a["error"] for a in meta["layout"]["attempts"]]
    assert errors[0] == "ответ не разобран: оборвался"
    assert errors[1].startswith("ошибок валидатора 1, первая — plan_opening")
    assert errors[2] is None
    assert meta["layout"]["model"] == str(cfg.models.layout.checkpoint)
    assert meta["errors"] == 0


def test_no_good_answer_within_attempts_is_refused(run, cfg):
    n = cfg.models.layout.attempts
    model = Fake(*[_without_door] * n)
    with pytest.raises(ModelError, match=f"за {n} попыток нет годного ответа; последняя "
                                         "причина — ошибок валидатора"):
        run(model)
    assert len(model.seeds) == n


def test_without_checkpoint_the_stub_answers(cfg, tmp_path):
    req = pipeline.PlanRun(plan=str(SIMPLE), text="", mode=MODE)
    out = pipeline.generate(req, SIMPLE.read_text(), tmp_path / "run", cfg)
    meta = json.loads((out / pipeline.META).read_text())
    assert meta["layout"] == {"model": "stub", "attempts": []}


def _tuned(cfg, **layout):
    """Настройки с другими полями [layout] (config/models.toml)."""
    settings = cfg.models.layout.model_copy(update=layout)
    return cfg.model_copy(update={"models": cfg.models.model_copy(update={"layout": settings})})


def test_bad_wall_is_redone_alone(run, cfg):
    """`wall_retry` (gf#213): брак на одной стене — досэмплируется она, а не весь дом."""
    model = Fake(_without_door, _good)
    meta, _ = run(model, _tuned(cfg, wall_retry=True))
    assert model.walls == [0]                                   # вход — на первой стене
    assert [a.get("wall") for a in meta["layout"]["attempts"]] == [None, 0]
    whole = Fake(_without_door, _good)
    run(whole)
    assert whole.walls == []                                    # по умолчанию — весь дом


def _short_windows(bare):
    """Годный ответ, у которого окна вдвое ниже, чем у стаба: на эталон из стабов не похож."""
    sheet = _good(bare)
    return sheet.model_copy(update={"facades": [f.model_copy(update={"elements": [
        e.model_copy(update={"h_m": e.h_m / 2}) if e.cls is ElementClass.WINDOW else e
        for e in f.elements]}) for f in sheet.facades]})


def test_best_of_n_takes_the_likeliest_answer(run, cfg, monkeypatch):
    """Лучший из N (gf#213): best_of ответов одной пачкой (один seed), из годных — с наибольшей
    density стен против эталона, а не первый годный."""
    reference = realism.walls([_good(tokens.bare(pipeline.walls(*_house(cfg))))] * 3)
    monkeypatch.setattr(pipeline, "_reference", lambda settings, without: reference)
    model = Fake(_short_windows, _good)
    meta, _ = run(model, _tuned(cfg, best_of=2))
    density = meta["layout"]["density"]
    assert meta["layout"]["chosen"] == 1 and density[1] > density[0]
    assert model.seeds == [cfg.models.layout.seed] * 2


def _house(cfg):
    plan = preprocess(SIMPLE.read_text(), MODE, cfg.plan)
    return stub.spec_model("", cfg.models.spec), plan


def test_reference_leaves_out_the_house_itself(at, sample):
    """Эталон «лучшего из N» — дома [layout.reference] без дома с именем плана запроса: иначе
    стены реального дома на реальном тесте находят в эталоне сами себя."""
    cfg = at("data")
    ref = cfg.models.layout.reference
    for name in ("a", "b"):
        store.write(sample.model_copy(update={"id": name, "source": ref.source,
                                              "split": ref.split}), cfg.data.paths.samples_dir)
    walls = len(sample.sheet.facades)
    assert len(pipeline._reference(cfg, "a")) == walls
    assert len(pipeline._reference(cfg, "other")) == 2 * walls
