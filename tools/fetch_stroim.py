#!/usr/bin/env python3
"""Проекты ИЖС со строим.дом.рф для реального теста (gf#328).

У сайта открытый API: список проектов и карточка проекта с этажностью, высотами, видом крыши,
материалами и номерами картинок; схема фасадов и план — JPEG с отметками уровней в метрах.
Условия ДОМ.РФ — «в личных некоммерческих целях», копирование и размещение — с согласия (п. 5.3):
картинки остаются в data/stroim/ вне git, в git — этот скрипт и наша разметка (markup/stroim/).

  python3 tools/fetch_stroim.py candidates --pages 4   кандидаты → data/stroim/candidates.json
  python3 tools/fetch_stroim.py get 24648 30112        карточка, картинки, лист PDF проекта

Кандидат — проект с 1–2 этажами над землёй, крышей, которую модуль строит над прямоугольником
(плоская, односкатная, двускатная, вальмовая), схемой фасадов из четырёх видов и планом. Годен ли
контур (прямоугольник, одна высота карниза), видно только глазами — отбор по листу.

Лист PDF — картинки проекта по странице, 1 pt = 1 px: разметка снимает координаты в pt листа,
как у FreeFarmhouse и Solar Decathlon (`genfacade/datasets/manual.py`). Страницы: фасады по
порядку схемы, затем планы. Идемпотентен: скачанное не качает заново.
"""
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image

SITE = 'https://xn--h1aieheg.xn--d1aqf.xn--p1ai'  # строим.дом.рф
OUT = Path('data/stroim')
HEADERS = {'User-Agent': 'GenFacade/1.0 (diploma research, ITMO)'}
PAUSE_S = 0.5           # между запросами: не нагружать сайт
FLOORS = '1-2'          # этажей над землёй, диапазон в формате API
ROOFS = {1: 'flat', 2: 'shed', 3: 'gable', 4: 'hip'}  # ROOF_TYPE API → вид крыши модуля
FACADES = 4             # видов в схеме фасадов
PAGE_SIZE = 50
PT_PER_PX = 72          # dpi листа: 1 pt = 1 px


def get(path):
    """GET к сайту; адрес — только строим.дом.рф."""
    url = SITE + path
    request = urllib.request.Request(url, headers=HEADERS)  # noqa: S310 — адрес сайта задан выше
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                data = response.read()
            time.sleep(PAUSE_S)
            return data
        except OSError as error:
            print(f'  повтор {attempt + 1}: {url}: {error}', file=sys.stderr)
            time.sleep(5)
    raise OSError(f'не ответил: {url}')


def card(pid):
    """Карточка проекта — из кэша data/stroim/cards/ или с сайта."""
    path = OUT / 'cards' / f'{pid}.json'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(f'/api/v1/projects/{pid}'))
    return json.loads(path.read_text())['payload']


def file_url(file_id):
    """Номер файла API → путь картинки: после префикса хранилища (до «3A») — пары знаков."""
    name = '3A'.join(file_id.split('3A')[1:])
    return '/img/' + '/'.join(name[i:i + 2] for i in range(0, len(name), 2)) + '/' + name


def summary(p):
    """Что из карточки нужно для отбора и разметки."""
    r = p['realization']
    return {'id': p['id'], 'name': p['name'], 'contractor': p['contractor']['name'],
            'floors': r.get('aerialPartFloors'), 'roof': ROOFS.get(r.get('roofType')),
            'building_height_m': r.get('buildingHeight'),
            'floor_height_m': r.get('livingQuartersHeight'), 'area_m2': r.get('houseArea'),
            'built_up_m2': r.get('builtUpArea'), 'facade_material': r.get('facadeMaterial'),
            'wall_mm': r.get('wallWidth'), 'attic': r.get('attic'),
            'facades': len(r.get('facadeScheme', {}).get('imageFileIds', [])),
            'plans': sum(len(x.get('imageFileIds', [])) for x in r.get('projectPlans', []))}


def candidates(pages):
    """Страницы списка с фильтром по этажам и крыше → проекты со схемой фасадов и планом."""
    roofs = ','.join(map(str, ROOFS))
    out, contractors = [], set()
    for page in range(pages):
        query = f'/api/v1/projects?page={page}&size={PAGE_SIZE}&aerialPartFloors={FLOORS}' \
                f'&roofType={roofs}&sort=published,asc'
        for item in json.loads(get(query))['payload']:
            s = summary(card(item['id']))
            if s['facades'] == FACADES and s['plans'] and s['contractor'] not in contractors:
                contractors.add(s['contractor'])  # подрядчик — один проект: дома разные
                out.append(s)
        print(f'страница {page}: кандидатов {len(out)}')
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'candidates.json').write_text(json.dumps(out, ensure_ascii=False, indent=1))
    return out


def images(pid):
    """Картинки проекта → data/stroim/<id>/: facade<n>.jpg, plan<k>-<n>.jpg; скачанное — мимо."""
    r = card(pid)['realization']
    names = [(f'facade{n}', f) for n, f in enumerate(r['facadeScheme']['imageFileIds'])]
    names += [(f'plan{k}-{n}', f) for k, plan in enumerate(r.get('projectPlans', []))
              for n, f in enumerate(plan.get('imageFileIds', []))]
    folder = OUT / str(pid)
    folder.mkdir(parents=True, exist_ok=True)
    new = 0
    for name, file_id in names:
        path = folder / f'{name}.jpg'
        if not path.exists():
            path.write_bytes(get(file_url(file_id)))
            new += 1
    return [folder / f'{name}.jpg' for name, _ in names], new


def sheet(pid, pictures):
    """Лист PDF из картинок проекта: страница на картинку, 1 pt = 1 px."""
    path = OUT / str(pid) / 'sheet.pdf'
    if path.exists():
        return False
    pages = [Image.open(p).convert('RGB') for p in pictures]
    pages[0].save(path, 'PDF', resolution=PT_PER_PX, save_all=True, append_images=pages[1:])
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('candidates').add_argument('--pages', type=int, default=4)
    sub.add_parser('get').add_argument('ids', type=int, nargs='+')
    args = parser.parse_args()
    if args.cmd == 'candidates':
        print(f'кандидатов: {len(candidates(args.pages))} → {OUT / "candidates.json"}')
        return
    for pid in args.ids:
        pictures, new = images(pid)
        made = sheet(pid, pictures)
        print(f'{pid}: картинок {len(pictures)}, скачано {new}, лист {"собран" if made else "был"}')


if __name__ == '__main__':
    main()
