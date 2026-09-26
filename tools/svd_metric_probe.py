#!/usr/bin/env python3
"""Проверка SVD-метрики регулярности фасада на вырожденность.

Метрика из Beyond Segmentation (EUROGRAPHICS 2026, arXiv:2604.09260):
бинарная маска одного класса раскладывается по SVD, счёт — сумма MSE между
маской и её rank-k приближениями для k = 1..25. Меньше = «регулярнее».

Реализовано заново по формулам статьи (CC BY 4.0), их код не использован —
в репозитории Beyond Segmentation нет файла LICENSE, а патч лосса производен
от ultralytics под AGPL.

Замкнутая форма, избавляющая от цикла:
    score(A) = (1/MN) · Σ_{i≥2} min(i−1, K) · σ_i²      (σ в шкале 0..1)
то есть метрика — взвешенная энергия неведущих сингулярных направлений.

Что показывает прогон: оптимум метрики **вырожден**. Маска идеальной осевой
решётки — внешнее произведение индикаторов строк и столбцов, то есть матрица
ранга 1, и все σ_i при i ≥ 2 равны нулю. Ровно ноль дают также пустая маска,
один прямоугольник и один ряд окон. Отсюда: метрика поощряет недогенерацию
и mode collapse, и штрафует легитимную архитектуру (витрину первого этажа).
"""
import numpy as np

H = W = 512
K = 25


def score(mask, k_max=K):
    """Прямой подсчёт по определению из статьи."""
    a = mask.astype(float)
    u, s, vt = np.linalg.svd(a, full_matrices=False)
    total = 0.0
    for k in range(1, k_max + 1):
        ak = u[:, :k] @ np.diag(s[:k]) @ vt[:k, :]
        total += np.mean(((a - ak) / 255.0) ** 2)
    return total


def score_closed(mask, k_max=K):
    """То же через замкнутую форму — совпадает до машинной точности."""
    a = mask.astype(float) / 255.0
    s = np.linalg.svd(a, compute_uv=False)
    return sum(min(i, k_max) * v * v for i, v in enumerate(s)) / (H * W)


def grid(rows, cols, jitter=0, drop=0.0):
    m = np.zeros((H, W), np.uint8)
    for r in range(rows):
        for c in range(cols):
            if np.random.rand() < drop:
                continue
            y = int(40 + r * (H - 80) / rows)
            x = int(40 + c * (W - 80) / cols)
            dy = np.random.randint(-jitter, jitter + 1) if jitter else 0
            dx = np.random.randint(-jitter, jitter + 1) if jitter else 0
            m[y + dy:y + dy + 40, x + dx:x + dx + 30] = 255
    return m


def main():
    np.random.seed(0)
    box = np.zeros((H, W), np.uint8); box[100:350, 100:350] = 255
    shop = grid(4, 6); shop[H - 110:H - 40, 40:W - 40] = 255
    cases = [
        ('идеальная решётка 5x6', grid(5, 6)),
        ('идеальная решётка 12x14', grid(12, 14)),
        ('один ряд окон', grid(1, 6)),
        ('один большой прямоугольник', box),
        ('ПУСТАЯ маска', np.zeros((H, W), np.uint8)),
        ('джиттер +-3 px', grid(5, 6, jitter=3)),
        ('решётка + витрина 1 этажа', shop),
        ('джиттер +-10 px', grid(5, 6, jitter=10)),
    ]
    print(f'{"маска":<30}{"score":>10}{"closed":>10}{"белых %":>10}')
    print('-' * 60)
    for name, m in cases:
        print(f'{name:<30}{score(m):>10.5f}{score_closed(m):>10.5f}{100 * (m > 0).mean():>9.1f}%')

    print('\n=== выгодно ли выбрасывать элементы (джиттер 5 px) ===')
    for d in (0.0, 0.5, 0.75, 0.9):
        np.random.seed(1)
        m = grid(5, 6, jitter=5, drop=d)
        print(f'  выброшено {int(d * 100):>2}%: score {score(m):.4f}, окон осталось ~{int(30 * (1 - d))}')


if __name__ == '__main__':
    main()
