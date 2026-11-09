#!/usr/bin/env python3
"""Окна и двери на листах фасадов строим.дом.рф детектором OWLv2 (gf#342).

OWLv2 (`google/owlv2-base-patch16-ensemble`, Apache-2.0) ищет по тексту «a window», «a door» —
без обучения на наших чертежах. Выход — рамки в px листа, по файлу JSON на дом: подсказка
агенту-разметчику и проверка его рамок. На процессоре — минуты на лист, на GPU — секунды.

  python3 tools/owl_boxes.py 55521 53626 -o outputs/owl      листы data/stroim/<id>/facade<n>.jpg
  python3 tools/owl_boxes.py --all -o outputs/owl            все дома из data/stroim/

Нужны transformers и torch (`pip install transformers`). Выход: `<out>/<id>.json` —
{"id", "sheets": [{"page", "size": [w, h], "sec", "boxes": [{"box", "cls", "score"}]}]}, и
`<out>/summary.json` — время загрузки модели, секунды на лист и на дом.
"""
import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from genfacade.schema import ElementClass  # noqa: E402
from tools.fetch_stroim import MAX_PIXELS  # noqa: E402

Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # схемы фасадов до ~200 Мп — см. fetch_stroim

MODEL = 'google/owlv2-base-patch16-ensemble'
QUERIES = {'a window': ElementClass.WINDOW, 'a door': ElementClass.DOOR}
THRESHOLD = 0.08        # ниже — шум; подобран на пяти домах (gf#342)
NMS_IOU = 0.5           # два пересекающихся запроса на один проём — оставить сильнейший
CONTAIN = 0.8           # рамка внутри другой (створка в окне) — лишняя
MIN_W, MAX_W = 0.015, 0.25   # ширина рамки в долях листа: масштаб неизвестен, отсев по доле
MIN_H, MAX_H = 0.02, 0.3
DATA = Path('data/stroim')
FACADE_GLOB = 'facade*.jpg'


@dataclass
class Box:
    box: list[float]    # x0, y0, x1, y1, px листа
    cls: ElementClass
    score: float


Detector = Callable[[Image.Image], list[Box]]


def overlap(a, b):
    """Площадь пересечения и IoU двух рамок."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    inter = max(0.0, w) * max(0.0, h)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter, (inter / union if union else 0.0)


def suppress(boxes: list[Box]) -> list[Box]:
    """Сильнейшие первыми; рамка, перекрытая сильнейшей (IoU или вложенность), снимается."""
    kept: list[Box] = []
    for b in sorted(boxes, key=lambda x: -x.score):
        area = (b.box[2] - b.box[0]) * (b.box[3] - b.box[1])
        pairs = [overlap(b.box, k.box) for k in kept]
        if not any(iou > NMS_IOU or inter / area > CONTAIN for inter, iou in pairs):
            kept.append(b)
    return kept


def plausible(b: Box, size) -> bool:
    """Размер рамки в долях листа: отсев щелей и целых стен."""
    width, height = (b.box[2] - b.box[0]) / size[0], (b.box[3] - b.box[1]) / size[1]
    return MIN_W < width < MAX_W and MIN_H < height < MAX_H


def detect(image: Image.Image, detector: Detector) -> list[Box]:
    """Рамки листа: отсев по размеру, потом NMS (иначе целая стена гасит свои окна); порядок —
    сверху вниз, слева направо."""
    found = suppress([b for b in detector(image) if plausible(b, image.size)])
    return sorted(found, key=lambda b: (b.box[1] // 50, b.box[0]))


def owl_detector(device: str | None = None) -> Detector:
    """OWLv2 на `device` (по умолчанию GPU, если есть): лист в квадрат с белыми полями справа и
    снизу — рамки остаются в px листа."""
    import torch  # noqa: PLC0415 — тяжёлый импорт нужен только детектору
    from transformers import Owlv2ForObjectDetection, Owlv2Processor  # noqa: PLC0415

    device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
    processor = Owlv2Processor.from_pretrained(MODEL)
    model = Owlv2ForObjectDetection.from_pretrained(MODEL).to(device).eval()
    classes = list(QUERIES.values())

    def run(image: Image.Image) -> list[Box]:
        side = max(image.size)
        square = Image.new('RGB', (side, side), (255, 255, 255))
        square.paste(image.convert('RGB'), (0, 0))
        inputs = processor(text=[list(QUERIES)], images=square, return_tensors='pt').to(device)
        with torch.no_grad():
            out = model(**inputs)
        found = processor.post_process_object_detection(
            out, threshold=THRESHOLD, target_sizes=torch.tensor([[side, side]]))[0]
        return [Box(box.tolist(), classes[label], float(score))
                for box, label, score in zip(found['boxes'], found['labels'], found['scores'],
                                             strict=True)]

    run(Image.new('RGB', (64, 64), (255, 255, 255)))  # прогрев: первый вызов на GPU долгий
    return run


def house_sheets(folder: Path) -> list[tuple[int, Path]]:
    """Листы фасадов дома: страница PDF — номер файла + 1 (facade0.jpg → страница 1)."""
    return [(int(p.stem.removeprefix('facade')) + 1, p)
            for p in sorted(folder.glob(FACADE_GLOB))]


def run_house(folder: Path, detector: Detector, clock=time.perf_counter) -> dict:
    """Один дом: рамки по листам и секунды на каждый."""
    sheets = []
    for page, path in house_sheets(folder):
        image = Image.open(path)
        start = clock()
        boxes = detect(image, detector)
        sheets.append({'page': page, 'size': list(image.size), 'sec': round(clock() - start, 3),
                       'boxes': [{**asdict(b), 'cls': b.cls.value} for b in boxes]})
    return {'id': folder.name, 'sheets': sheets}


def run(ids: list[str], data: Path, out: Path, make: Callable[[], Detector]) -> dict:
    """Дома → `<out>/<id>.json` и `summary.json` (время модели, листов и домов)."""
    out.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    detector = make()
    summary: dict = {'model_load_sec': round(time.perf_counter() - start, 2), 'houses': {},
                     'failed': []}
    for pid in ids:
        try:  # битая картинка одного дома не роняет пакет: дом — в failed
            result = run_house(data / pid, detector)
        except OSError as error:
            summary['failed'].append(pid)
            print(pid, 'пропущен —', error, flush=True)
            continue
        (out / f'{pid}.json').write_text(json.dumps(result, ensure_ascii=False))
        secs = [s['sec'] for s in result['sheets']]
        summary['houses'][pid] = {'sheets': len(secs), 'sec': round(sum(secs), 2),
                                  'boxes': sum(len(s['boxes']) for s in result['sheets'])}
        print(pid, summary['houses'][pid], flush=True)
    summary['sheets_total'] = sum(h['sheets'] for h in summary['houses'].values())
    summary['sec_total'] = round(sum(h['sec'] for h in summary['houses'].values()), 2)
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('ids', nargs='*', help='номера проектов')
    parser.add_argument('--all', action='store_true', help='все дома из папки данных')
    parser.add_argument('--data', type=Path, default=DATA)
    parser.add_argument('-o', '--out', type=Path, default=Path('outputs/owl'))
    args = parser.parse_args()
    ids = sorted(p.name for p in args.data.iterdir() if p.is_dir() and house_sheets(p)) \
        if args.all else args.ids
    if not ids:
        parser.error('нужны номера проектов или --all')
    summary = run(ids, args.data, args.out, owl_detector)
    print(f'листов {summary["sheets_total"]}, {summary["sec_total"]} с, '
          f'модель грузилась {summary["model_load_sec"]} с, пропущено {len(summary["failed"])}')


if __name__ == '__main__':
    main()
