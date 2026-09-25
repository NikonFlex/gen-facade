"""Парсер разметки CMP Facade Database.

ВАЖНО про оси. В XML координаты нормализованы в [0,1], но соглашение
не интуитивное и нигде на странице датасета не описано:

    <x> — ВЕРТИКАЛЬНАЯ ось (строка, масштабируется высотой H)
    <y> — ГОРИЗОНТАЛЬНАЯ ось (столбец, масштабируется шириной W)

То есть (row, col), как в MATLAB, а не (x, y) как в графике.
Проверено эмпирически сверкой с масками PNG: при таком прочтении
медианный IoU с bbox класса = 0.978, при обратном = 0.000.

Каждый объект — ровно 2 значения x и 2 значения y, то есть
axis-aligned прямоугольник. Исключений в датасете нет (51769/51769).

Формат XML неоднороден: в части файлов значения записаны в одну строку,
в части обёрнуты переводами строк. Регулярки ниже терпимы к пробелам.
"""
import re

NUM = r'\s*([-\d.eE+]+)\s*'


def parse(xml_path):
    """-> список dict(label, name, x0, x1, y0, y1) в нормализованных координатах.

    x0/x1 — вертикаль (доли высоты), y0/y1 — горизонталь (доли ширины).
    """
    text = open(xml_path).read()
    objs = []
    for m in re.finditer(r'<object>(.*?)</object>', text, re.S):
        body = m.group(1)
        xs = [float(v) for v in re.findall(r'<x>' + NUM + r'</x>', body)]
        ys = [float(v) for v in re.findall(r'<y>' + NUM + r'</y>', body)]
        objs.append(dict(
            label=int(re.search(r'<label>\s*(\d+)\s*</label>', body).group(1)),
            name=re.search(r'<labelname>\s*(\S*)\s*</labelname>', body).group(1),
            x0=min(xs), x1=max(xs), y0=min(ys), y1=max(ys),
        ))
    return objs


def to_pixels(obj, width, height):
    """-> (left, top, right, bottom) в пикселях, как ожидает PIL/ImageDraw."""
    return (obj['y0'] * width, obj['x0'] * height,
            obj['y1'] * width, obj['x1'] * height)
