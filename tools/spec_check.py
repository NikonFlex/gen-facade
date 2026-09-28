"""Проверки порядка «входящие → спеки» перед коммитом (docs/SPEC-DRIVEN.md).

Запуск: python3 tools/spec_check.py [корень репозитория]
Код возврата 0 — всё в порядке, 1 — есть нарушения (печатаются по строке).
"""

import hashlib
import re
import sys
from pathlib import Path

import yaml

INCOMING = Path("docs/incoming")
SPECS = Path("specs")
SERVICE_FILES = {"README.md", "index.yaml"}
HEADER_FIELDS = ("Статус", "Источники:", "Владелец дельт")
# Спека не хранит состояние задач: рядом со ссылкой на задачу этих слов быть не должно.
TASK_REF = re.compile(r"(gf#\d+|#\d+|gf-\d{4})")
TASK_STATE = re.compile(r"\b(открыт[аы]?|закрыт[аы]?|сделан[аы]?|в работе|готов[аы]?)\b", re.I)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_incoming(root: Path) -> list[str]:
    """Каждый входящий файл — в индексе, каждая запись — на живой файл с тем же sha256."""
    index = yaml.safe_load((root / INCOMING / "index.yaml").read_text(encoding="utf-8")) or []
    problems = []
    listed = set()
    for entry in index:
        path = root / entry["path"]
        listed.add(path.name)
        if not path.exists():
            problems.append(f"индекс: нет файла {entry['path']}")
            continue
        if sha256(path) != entry.get("sha256"):
            problems.append(f"индекс: sha256 не совпадает у {entry['path']} — входящие не правятся")
        problems += check_distilled(root, entry)
    for path in (root / INCOMING).iterdir():
        if path.is_file() and path.name not in SERVICE_FILES and path.name not in listed:
            problems.append(f"индекс: файла {path.name} нет в index.yaml")
    return problems


def check_distilled(root: Path, entry: dict) -> list[str]:
    if entry.get("status") != "distilled":
        return []
    targets = entry.get("distilled_into") or []
    if not targets:
        return [f"индекс: {entry['path']} — distilled, но distilled_into пуст"]
    return [f"индекс: {entry['path']} ссылается на несуществующую {t}"
            for t in targets if not (root / t).exists()]


def spec_files(root: Path) -> list[Path]:
    return sorted(p for p in (root / SPECS).glob("*.md") if p.name != "README.md")


def check_spec(path: Path) -> list[str]:
    """Шапка со статусом, источниками и владельцем; непустое «Открыто»; без состояния задач."""
    text = path.read_text(encoding="utf-8")
    head = text.split("\n## ", 1)[0]
    problems = [f"{path.name}: в шапке нет «{field}»" for field in HEADER_FIELDS
                if field not in head]
    if not open_section(text):
        problems.append(f"{path.name}: раздел «## Открыто» пуст или отсутствует")
    for n, line in enumerate(text.splitlines(), 1):
        if TASK_REF.search(line) and TASK_STATE.search(line):
            problems.append(f"{path.name}:{n}: рядом со ссылкой на задачу её состояние")
    return problems


def open_section(text: str) -> str:
    match = re.search(r"^## Открыто\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else ""


def domain_entities(root: Path) -> list[str]:
    """Сущности из последней колонки таблицы доменов в specs/README.md."""
    text = (root / SPECS / "README.md").read_text(encoding="utf-8")
    table = text.split("## Домены", 1)[1].split("\n## ", 1)[0]
    names = []
    for row in table.splitlines():
        cells = [c.strip() for c in row.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[2] not in ("—", "Ключевые сущности", "---"):
            names += [n.strip() for n in cells[2].split(",")]
    return names


def check_entities(root: Path) -> list[str]:
    """Каждая сущность из карты объявлена (### Имя) ровно в одной спеке."""
    problems = []
    for name in domain_entities(root):
        owners = [p.name for p in spec_files(root)
                  if re.search(rf"^### {re.escape(name)}\s*$", p.read_text(encoding="utf-8"), re.M)]
        if len(owners) != 1:
            where = ", ".join(owners) or "нигде"
            problems.append(f"сущность {name} объявлена не в одной спеке: {where}")
    return problems


def run(root: Path) -> list[str]:
    problems = check_incoming(root) + check_entities(root)
    for path in spec_files(root):
        problems += check_spec(path)
    return problems


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    problems = run(root)
    for problem in problems:
        print(problem)
    print("спеки в порядке" if not problems else f"нарушений: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
