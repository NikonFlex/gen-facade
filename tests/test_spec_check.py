import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import spec_check  # noqa: E402

SPEC = """# Домен

> **Статус: provisional.**
> Источники: docs/incoming/doc.md.
> Владелец дельт: хозяин.

## Сущности

### Thing

## Открыто

- вопрос
"""

README = """# Спеки

## Домены

| Спека | Хранит | Ключевые сущности |
|---|---|---|
| domain.md | всё | Thing |

## Приоритет источников
"""


def write_repo(root: Path) -> None:
    incoming = root / "docs" / "incoming"
    incoming.mkdir(parents=True)
    (incoming / "doc.md").write_text("как получено", encoding="utf-8")
    digest = hashlib.sha256((incoming / "doc.md").read_bytes()).hexdigest()
    (incoming / "index.yaml").write_text(
        f"- path: docs/incoming/doc.md\n  status: distilled\n  sha256: {digest}\n"
        "  distilled_into:\n  - specs/domain.md\n",
        encoding="utf-8",
    )
    (root / "specs").mkdir()
    (root / "specs" / "README.md").write_text(README, encoding="utf-8")
    (root / "specs" / "domain.md").write_text(SPEC, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    write_repo(tmp_path)
    return tmp_path


def test_clean_repo_passes(repo):
    assert spec_check.run(repo) == []


def test_real_repo_passes():
    assert spec_check.run(Path(__file__).resolve().parents[1]) == []


def test_edited_incoming_is_caught(repo):
    (repo / "docs/incoming/doc.md").write_text("поправили", encoding="utf-8")
    assert any("sha256" in p for p in spec_check.run(repo))


def test_unlisted_incoming_is_caught(repo):
    (repo / "docs/incoming/new.md").write_text("новый", encoding="utf-8")
    assert any("new.md" in p for p in spec_check.run(repo))


def test_distilled_into_missing_spec_is_caught(repo):
    (repo / "specs/domain.md").rename(repo / "specs/other.md")
    assert any("несуществующую" in p for p in spec_check.run(repo))


def test_empty_open_section_is_caught(repo):
    spec = repo / "specs/domain.md"
    spec.write_text(SPEC.replace("- вопрос\n", ""), encoding="utf-8")
    assert any("Открыто" in p for p in spec_check.run(repo))


def test_missing_owner_is_caught(repo):
    spec = repo / "specs/domain.md"
    spec.write_text(SPEC.replace("> Владелец дельт: хозяин.\n", ""), encoding="utf-8")
    assert any("Владелец дельт" in p for p in spec_check.run(repo))


def test_entity_declared_twice_is_caught(repo):
    (repo / "specs/twin.md").write_text(SPEC, encoding="utf-8")
    assert any("Thing" in p for p in spec_check.run(repo))


def test_task_state_next_to_ref_is_caught(repo):
    spec = repo / "specs/domain.md"
    spec.write_text(SPEC + "\nСм. gf#12, задача закрыта.\n", encoding="utf-8")
    assert any("состояние" in p for p in spec_check.run(repo))
