#!/usr/bin/env python3
"""Зеркалирование чертежей Solar Decathlon из Wayback.

Источник умирает: solardecathlon.gov переименован, старые пути отдают мягкий
404, живо только в веб-архиве. Скрипт выгружает список через CDX, дедуплицирует
по имени файла, качает и сразу проверяет каждый комплект: вектор это или скан,
сколько листов наружных фасадов, стоит ли штамп PUBLIC DOMAIN.

Результат — data/solar-decathlon/ и manifest.json рядом.
"""
import json, re, subprocess, sys, time
from pathlib import Path

OUT = Path('data/solar-decathlon')
CDX = ("http://web.archive.org/cdx/search/cdx?url=solardecathlon.gov&matchType=domain"
       "&filter=original:.*(drawings|_cd)\\.pdf&filter=statuscode:200"
       "&fl=timestamp,original,length&limit=2000")

def cdx_rows():
    for attempt in range(4):
        r = subprocess.run(['curl','-s','--max-time','180',CDX], capture_output=True, text=True)
        rows = [l.split() for l in r.stdout.strip().splitlines() if len(l.split()) == 3]
        if rows: return rows
        time.sleep(10)
    sys.exit('CDX не ответил')

def pick(rows):
    """По одному снапшоту на файл — самый крупный, он обычно самый полный."""
    best = {}
    for ts, url, ln in rows:
        try: ln = int(ln)
        except ValueError: continue
        name = url.rsplit('/', 1)[-1].lower()
        if name not in best or ln > best[name][2]:
            best[name] = (ts, url, ln)
    return best

def year_of(url):
    m = re.search(r'/(20\d\d)/', url)
    return m.group(1) if m else 'other'

def inspect(path):
    try:
        import pymupdf
        d = pymupdf.open(path)
    except Exception as e:
        return {'ok': False, 'error': str(e)[:120]}
    elev, pd_pages, best = [], 0, 0
    for i in range(d.page_count):
        try: t = d[i].get_text()
        except Exception: continue
        if re.search(r'EXTERIOR\s+ELEVATION', t, re.I): elev.append(i)
        if 'PUBLIC DOMAIN' in t.upper(): pd_pages += 1
    for i in elev[:6]:
        try: best = max(best, sum(len(p['items']) for p in d[i].get_drawings()))
        except Exception: pass
    res = {'ok': True, 'pages': d.page_count, 'elevation_sheets': len(elev),
           'elevation_pages': elev[:12], 'public_domain_pages': pd_pages,
           'max_vector_items_on_elevation': best,
           'vector': best > 500}
    d.close(); return res

def main():
    rows = cdx_rows()
    best = pick(rows)
    print(f'CDX строк: {len(rows)}, уникальных файлов: {len(best)}', flush=True)
    manifest, done, failed = [], 0, 0
    for name, (ts, url, ln) in sorted(best.items()):
        y = year_of(url)
        dest = OUT / y / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.stat().st_size < 1000:
            wb = f'https://web.archive.org/web/{ts}if_/{url}'
            ok = False
            for attempt in range(3):
                r = subprocess.run(['curl','-sL','--max-time','900','-o',str(dest),wb])
                if r.returncode == 0 and dest.exists() and dest.stat().st_size > 10000:
                    ok = True; break
                time.sleep(15)
            if not ok:
                failed += 1
                print(f'  ✗ {name}', flush=True)
                manifest.append({'name': name, 'url': url, 'downloaded': False}); continue
        info = inspect(dest)
        done += 1
        manifest.append({'name': name, 'year': y, 'url': url, 'wayback_ts': ts,
                         'size': dest.stat().st_size, 'downloaded': True, **info})
        print(f'  ✓ {name}: {info.get("pages","?")} стр., фасадов {info.get("elevation_sheets","?")}, '
              f'вектор {info.get("vector")}, PD {info.get("public_domain_pages","?")}', flush=True)
        (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    ok = [m for m in manifest if m.get('downloaded')]
    vec = [m for m in ok if m.get('vector')]
    print(f'\nскачано {done}, не удалось {failed}')
    print(f'векторных комплектов: {len(vec)} из {len(ok)}')
    print(f'листов наружных фасадов суммарно: {sum(m.get("elevation_sheets",0) for m in vec)}')
    print(f'комплектов со штампом PUBLIC DOMAIN: {sum(1 for m in vec if m.get("public_domain_pages",0)>0)}')

main()
