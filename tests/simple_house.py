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
TOP_RIGHT = '<rect x="800" y="100" width="300"'  # кусок верхней стены справа от верхнего окна


def top_right_shifted(dy: int) -> tuple[str, str]:
    """Замена для simple_svg: кусок верхней стены справа от окна сдвинут вниз на dy px."""
    return TOP_RIGHT, f'<rect x="800" y="{100 + dy}" width="300"'


# Замены для simple_svg: L-контур — правый верхний угол дома вырезан. Справа от верхнего окна
# стена уходит вниз до y = 300 и идёт вправо; правое окно снято вместе с верхом правой стены.
L_SHAPE = (
    ('<rect x="800" y="100" width="300" height="15" fill="#000000" />',
     '<rect x="800" y="100" width="30" height="15" fill="#000000" />'
     '<rect x="815" y="100" width="15" height="215" fill="#000000" />'
     '<rect x="815" y="300" width="285" height="15" fill="#000000" />'),
    ('<rect x="1085" y="100" width="15" height="150" fill="#000000" />', ""),
    ('<rect x="1085" y="250" width="15" height="150" fill="#99ccff" />', ""),
    ('<rect x="1085" y="400" width="15" height="200" fill="#000000" />',
     '<rect x="1085" y="300" width="15" height="300" fill="#000000" />'),
)
