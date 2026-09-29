import tomllib
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_installed_package_matches_repo():
    # Ловит устаревшую установку: pyproject поменяли, а pip install -e . не перезапустили.
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert version("genfacade") == declared
