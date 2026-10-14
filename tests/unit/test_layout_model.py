"""Модель шага 4 в конвейере (gf#107): брак — заново с новым seed, предел попыток — отказ.

Модель подменяется: тесты не учат и не грузят чекпойнт, поэтому идут и без torch.
"""

import json

import pytest
from simple_house import SIMPLE

from genfacade import pipeline
from genfacade.models import stub
from genfacade.models.stub import ModelError
from genfacade.schema import ElementClass, Mode
from genfacade.train.tokens import TokenError

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
    """Подмена обученной модели: ответы по очереди — функция от стен или исключение."""

    def __init__(self, *answers):
        self.answers, self.seeds = list(answers), []

    def prompt(self, bare, mode, cfg):
        return mode

    def answer(self, prompt, bare, seed, cfg):
        self.seeds.append(seed)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer(bare)


@pytest.fixture
def run(monkeypatch, cfg, tmp_path):
    """Прогон простого дома с подменённой моделью; вернуть meta.json и модель."""
    def go(model):
        monkeypatch.setattr(pipeline, "trained_model", lambda settings: model)
        req = pipeline.PlanRun(plan=str(SIMPLE), text="", mode=MODE)
        out = pipeline.generate(req, SIMPLE.read_text(), tmp_path / "run", cfg)
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
