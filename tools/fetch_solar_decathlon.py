#!/usr/bin/env python3
"""Зеркалирование чертежей Solar Decathlon из Wayback.

Источник умирает: solardecathlon.gov переименован, старые пути отдают мягкий
404, живо только в веб-архиве. Скрипт выгружает список через CDX, дедуплицирует
по имени файла, качает и сразу проверяет каждый комплект: вектор это или скан,
сколько листов наружных фасадов, стоит ли штамп PUBLIC DOMAIN.

Идемпотентен: уже скачанное не качает заново, только перепроверяет.
Результат — data/solar-decathlon/ и manifest.json рядом.
"""
import json
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path('data/solar-decathlon')
CDX = ('https://web.archive.org/cdx/search/cdx?url=solardecathlon.gov&matchType=domain'
       '&filter=original:.*(drawings|_cd)\\.pdf&filter=statuscode:200'
       '&fl=timestamp,original,length&limit=2000')
HEADERS = {'User-Agent': 'GenFacade-mirror/1.0 (diploma research, ITMO)'}
# Лист фасада, напечатанный из CAD, даёт тысячи векторных примитивов, скан — единицы.
MIN_VECTOR_ITEMS = 500


def fetch(url, timeout):
    """Все запросы идут только в веб-архив по https — схему проверяем явно."""
    if not url.startswith('https://web.archive.org/'):
        raise ValueError(f'неожиданный URL: {url}')
    request = urllib.request.Request(url, headers=HEADERS)  # noqa: S310 — схема проверена выше
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 — схема проверена выше


def with_retries(action, attempts, pause):
    """Wayback периодически отваливается; пустой результат — повод повторить."""
    for _ in range(attempts):
        try:
            result = action()
        except OSError as error:
            print(f'    повтор после ошибки: {error}', file=sys.stderr)
            result = None
        if result:
            return result
        time.sleep(pause)
    return None


def cdx_rows():
    def query():
        with fetch(CDX, timeout=180) as response:
            text = response.read().decode()
        return [line.split() for line in text.splitlines() if len(line.split()) == 3]

    rows = with_retries(query, attempts=4, pause=10)
    if not rows:
        sys.exit('CDX не ответил')
    return rows


def pick(rows):
    """По одному снапшоту на файл — самый крупный, он обычно самый полный."""
    best = {}
    for timestamp, url, length in rows:
        if not length.isdigit():
            continue
        name = url.rsplit('/', 1)[-1].lower()
        if name not in best or int(length) > best[name][2]:
            best[name] = (timestamp, url, int(length))
    return best


def year_of(url):
    match = re.search(r'/(20\d\d)/', url)
    return match.group(1) if match else 'other'


def download(timestamp, url, dest):
    """True, если на диске оказался правдоподобно полный файл."""
    wayback = f'https://web.archive.org/web/{timestamp}if_/{url}'

    def attempt():
        with fetch(wayback, timeout=900) as response, open(dest, 'wb') as out:
            shutil.copyfileobj(response, out)
        return dest.stat().st_size > 10_000

    return bool(with_retries(attempt, attempts=3, pause=15))


def scan_pages(doc):
    """Номера листов наружных фасадов и число страниц со штампом public domain."""
    elevation, stamped = [], 0
    for index, page in enumerate(doc):
        try:
            text = page.get_text()
        except Exception as error:  # битая страница не должна ронять весь комплект
            print(f'    страница {index}: {error}', file=sys.stderr)
            continue
        if re.search(r'EXTERIOR\s+ELEVATION', text, re.IGNORECASE):
            elevation.append(index)
        if 'PUBLIC DOMAIN' in text.upper():
            stamped += 1
    return elevation, stamped


def max_vector_items(doc, pages):
    """Сколько векторных примитивов на самом насыщенном из первых листов фасада."""
    best = 0
    for index in pages[:6]:
        try:
            items = sum(len(path['items']) for path in doc[index].get_drawings())
        except Exception as error:
            print(f'    лист {index}: {error}', file=sys.stderr)
            continue
        best = max(best, items)
    return best


def inspect(path):
    import pymupdf  # тяжёлая зависимость нужна только здесь

    try:
        doc = pymupdf.open(path)
    except Exception as error:
        return {'ok': False, 'error': str(error)[:120]}
    elevation, stamped = scan_pages(doc)
    best = max_vector_items(doc, elevation)
    pages = doc.page_count
    doc.close()
    return {'ok': True, 'pages': pages, 'elevation_sheets': len(elevation),
            'elevation_pages': elevation[:12], 'public_domain_pages': stamped,
            'max_vector_items_on_elevation': best, 'vector': best > MIN_VECTOR_ITEMS}


def process(name, entry):
    timestamp, url, _length = entry
    year = year_of(url)
    dest = OUT / year / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    missing = not dest.exists() or dest.stat().st_size < 1000
    if missing and not download(timestamp, url, dest):
        print(f'  ✗ {name}', flush=True)
        return {'name': name, 'url': url, 'downloaded': False}
    info = inspect(dest)
    print(f'  ✓ {name}: {info.get("pages", "?")} стр., '
          f'фасадов {info.get("elevation_sheets", "?")}, вектор {info.get("vector")}, '
          f'PD {info.get("public_domain_pages", "?")}', flush=True)
    return {'name': name, 'year': year, 'url': url, 'wayback_ts': timestamp,
            'size': dest.stat().st_size, 'downloaded': True, **info}


def summarize(manifest):
    ok = [entry for entry in manifest if entry.get('downloaded')]
    vector = [entry for entry in ok if entry.get('vector')]
    sheets = sum(entry.get('elevation_sheets', 0) for entry in vector)
    stamped = sum(1 for entry in vector if entry.get('public_domain_pages', 0) > 0)
    print(f'\nскачано {len(ok)}, не удалось {len(manifest) - len(ok)}')
    print(f'векторных комплектов: {len(vector)} из {len(ok)}')
    print(f'листов наружных фасадов суммарно: {sheets}')
    print(f'комплектов со штампом PUBLIC DOMAIN: {stamped}')


def main():
    best = pick(cdx_rows())
    print(f'уникальных файлов: {len(best)}', flush=True)
    manifest = []
    for name, entry in sorted(best.items()):
        manifest.append(process(name, entry))
        # Опись пишется после каждого файла: обрыв архива не теряет сделанное.
        (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    summarize(manifest)


if __name__ == '__main__':
    main()
