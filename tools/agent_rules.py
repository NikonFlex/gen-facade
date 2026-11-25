"""Правила и навыки агентов из общего источника.

    python3 tools/agent_rules.py            проверить: копии совпадают с docs/agents/
    python3 tools/agent_rules.py --write    пересобрать копии
    python3 tools/agent_rules.py --selftest

Источник — `docs/agents/<тема>.md`. Копии с заголовком своей среды:
`.claude/rules/<тема>.md` (Claude Code подгружает по `paths`) и `.cursor/rules/<тема>.mdc`
(Cursor — по `globs`). Codex подгружать по путям не умеет: AGENTS.md велит прочитать сам
файл из `docs/agents/`. Копии пересобирают из источника. Из .agents/skills/ собираются
копии .claude/skills/ и относительные ссылки .bb/skills/.
"""

from __future__ import annotations

import sys
import tempfile
from os.path import relpath
from pathlib import Path

from script_common import ROOT, report, write_files

SOURCE = Path("docs/agents")
SKILL_SOURCE = Path(".agents/skills")
BB_SKILLS = Path(".bb/skills")
CLAUDE_SKILLS = Path(".claude/skills")
#: Тема → пути, при работе с которыми правило подгружается. Одно объявление на обе среды.
TOPICS = {
    "code": ["**/*.py", "**/*.toml", "**/*.css", "**/*.js", "requirements*.txt"],
    "specs": ["openspec/**", "docs/incoming/**", "docs/examples/project/**"],
    "tasks": ["docs/tasks/**"],
    # схема пайплайна диплома целиком — при работе с кодом, спеками, тестами, планом
    "scheme": ["genfacade/**", "openspec/**", "tests/**", "docs/dev-plan.md",
               "docs/assets/facade-modules.*"],
}
NOTE = ("<!-- Копия docs/agents/{topic}.md — правится там, "
        "пересборка: tools/agent_rules.py --write -->")


def describe(body: str) -> str:
    """Первый абзац после заголовка — описание правила для Cursor."""
    paragraphs = [p for p in body.split("\n\n")[1:] if p.strip()]
    return " ".join(paragraphs[0].split()) if paragraphs else ""


def claude_copy(topic: str, body: str) -> str:
    paths = "\n".join(f'  - "{p}"' for p in TOPICS[topic])
    return f"---\npaths:\n{paths}\n---\n\n{NOTE.format(topic=topic)}\n\n{body}"


def cursor_copy(topic: str, body: str) -> str:
    description = describe(body).replace('"', "'")
    globs = ",".join(TOPICS[topic])
    return (f'---\ndescription: "{description}"\nglobs: {globs}\nalwaysApply: false\n---\n\n'
            f"{NOTE.format(topic=topic)}\n\n{body}")


def expected(root: Path) -> dict[Path, str]:
    out = {}
    for topic in TOPICS:
        body = (root / SOURCE / f"{topic}.md").read_text(encoding="utf-8")
        out[Path(".claude/rules") / f"{topic}.md"] = claude_copy(topic, body)
        out[Path(".cursor/rules") / f"{topic}.mdc"] = cursor_copy(topic, body)
    return out | expected_skills(root)


def expected_skills(root: Path) -> dict[Path, str]:
    return {CLAUDE_SKILLS / path.relative_to(root / SKILL_SOURCE): path.read_text(encoding="utf-8")
            for path in (root / SKILL_SOURCE).glob("*/SKILL.md")}


def skill_links(root: Path, write: bool) -> list[str]:
    folder = root / BB_SKILLS
    sources = {path.parent.name: path.parent for path in (root / SKILL_SOURCE).glob("*/SKILL.md")}
    problems = []
    for name, source in sorted(sources.items()):
        target = folder / name
        relative = Path(relpath(source, folder))
        if target.is_symlink() and target.readlink() == relative:
            continue
        if write and (target.is_symlink() or not target.exists()):
            folder.mkdir(parents=True, exist_ok=True)
            target.unlink(missing_ok=True)
            target.symlink_to(relative, target_is_directory=True)
        else:
            problems.append(f"{BB_SKILLS / name} должен ссылаться на {SKILL_SOURCE / name}")
    for folder in (root / BB_SKILLS, root / CLAUDE_SKILLS):
        if folder.is_dir():
            problems += [f"лишний навык {path.relative_to(root)}"
                         for path in sorted(folder.iterdir()) if path.name not in sources
                         and (path.is_symlink() or (path / "SKILL.md").is_file())]
    return problems


def run(root: Path, write: bool) -> list[str]:
    problems = []
    for path, text in expected(root).items():
        target = root / path
        if write:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        elif not target.exists() or target.read_text(encoding="utf-8") != text:
            problems.append(f"{path} не совпадает с источником — пересобрать: --write")
    return problems + skill_links(root, write)


def selftest() -> int:
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        root = write_files(Path(tmp), {f"{SOURCE}/{t}.md": f"# {t}\n\nПро {t}.\n" for t in TOPICS})
        run(root, write=True)
        if problems := run(root, write=False):
            bad.append(f"после сборки копии не совпадают: {problems}")
        claude = (root / ".claude/rules/code.md").read_text(encoding="utf-8")
        cursor = (root / ".cursor/rules/code.mdc").read_text(encoding="utf-8")
        if '  - "**/*.py"' not in claude or "globs: **/*.py," not in cursor \
                or 'description: "Про code."' not in cursor:
            bad.append("заголовок копии не тот")
        (root / ".cursor/rules/tasks.mdc").write_text("правка руками", encoding="utf-8")
        (root / SOURCE / "specs.md").write_text("# specs\n\nИначе.\n", encoding="utf-8")
        found = run(root, write=False)
        if len(found) != 3:
            bad.append(f"правка копии и источника не пойманы: {found}")
    return report(bad + skill_selftest(), "сборка правил и навыков, расхождение копий и ссылок")


def skill_selftest() -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        files = {f"{SOURCE}/{topic}.md": f"# {topic}\n" for topic in TOPICS}
        files[f"{SKILL_SOURCE}/task/SKILL.md"] = "# Task\n"
        root = write_files(Path(tmp), files)
        copy = root / CLAUDE_SKILLS / "task/SKILL.md"
        problems = run(root, write=True)
        link = root / BB_SKILLS / "task"
        if problems or not link.is_symlink():
            return [f"сборка ссылки навыка BB не прошла: {problems}"]
        if (link / "SKILL.md").read_bytes() != copy.read_bytes():
            return ["сборка навыка BB дала неверную ссылку или копию"]
        link.unlink()
        link.symlink_to("../missing", target_is_directory=True)
        (root / BB_SKILLS / "extra").symlink_to("../missing", target_is_directory=True)
        copy.write_text("# Расходится\n", encoding="utf-8")
        found = run(root, write=False)
        if len(found) != 3:
            return [f"битая ссылка, лишняя ссылка или правка копии не найдены: {found}"]
    return []


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    problems = run(ROOT, write="--write" in sys.argv)
    for problem in problems:
        print(problem)
    print("правила сред совпадают с источником" if not problems else f"нарушений: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
