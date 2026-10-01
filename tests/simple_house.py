"""Простой дом для тестов (gf#58): путь к плану и куски его SVG, которые тесты портят.

План 10 × 5 м в формате GenPlan (tests/fixtures/make_simple_house.py): вход 0.9 м и окна 1.2 м
снизу, 1.0 м слева, 2.0 м сверху, 1.5 м справа.
"""

from pathlib import Path

SIMPLE = Path(__file__).parent / "fixtures" / "simple_house.svg"
LEAF = '<rect x="800" y="495" width="5" height="90" fill="#000000" />'  # створка входа
# Внутренняя стена заходит в полосу верхнего окна плана (дефект GenPlan): запретная зона в окне.
WALL_INTO_WINDOW = '<rect x="700" y="108" width="9" height="200" fill="#000000" />'


def before_leaf(extra: str) -> tuple[str, str]:
    """Замена для фикстуры simple_svg: вставить кусок SVG перед створкой входа."""
    return LEAF, extra + LEAF
