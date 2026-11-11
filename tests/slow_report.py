"""Датчик долгих тестов (gf#443): тест быстрого набора дольше порога `slow_after_s`
(`pyproject.toml`) — кандидат в метку `slow`. Время теста — подготовка и вызов вместе: тяжёлая
фикстура модуля ложится на первый тест, которому она нужна.

Датчик называет, а не валит прогон: время зависит от нагрузки машины (11.11.2026 хук на той же
правке шёл и 2, и 25 минут), проверка по нему мигала бы.
"""

from collections import defaultdict

SLOW = "slow"
TIMED = ("setup", "call")


class Timings:
    """Время тестов прогона по отчётам pytest; под xdist отчёты приходят в главный процесс."""

    def __init__(self) -> None:
        self.seconds: defaultdict[str, float] = defaultdict(float)
        self.marked: set[str] = set()

    def add(self, nodeid: str, when: str, duration: float, keywords) -> None:
        if when in TIMED:
            self.seconds[nodeid] += duration
        if SLOW in keywords:
            self.marked.add(nodeid)

    def unmarked_over(self, limit: float) -> list[tuple[str, float]]:
        """Тесты без метки `slow` дольше limit секунд, долгие — первыми."""
        found = [(n, s) for n, s in self.seconds.items() if s > limit and n not in self.marked]
        return sorted(found, key=lambda x: -x[1])
