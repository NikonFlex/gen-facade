# Braille в смотрелке Gen Facade

Braille читает состояние интерфейса в JSON. Здесь используются исходные
браузерный API и CLI [agent-braille](https://github.com/blurman-ai/agent-braille)
на ревизии из [NOTICE](NOTICE).

## Запуск

Из корня проекта в окружении со смотрелкой (`python3 -m pip install -e '.[viewer]'`).

```sh
AGENT_API=1 genfacade serve
```

При `AGENT_API=1` сервер подключает браузерный пакет до кода смотрелки.
Агенту доступны `window.stalker` и его алиас `window.__agent`. При обычном
запуске адрес скрипта отвечает 404. Для самой смотрелки Node.js не нужен.

## Сценарий на Chromium

Для раннера нужен Node.js 20.19 или новее. Команды из корня репозитория.

```sh
npm ci --prefix braille/upstream --omit=dev
(cd braille/upstream && npx playwright-core install chromium)
node braille/upstream/bin/braille.mjs run tests/fixtures/braille/simple-house.json \
    --base http://127.0.0.1:8000 --sensors
```

Сценарий выбирает `simple_house`, строит фасады и проверяет наличие листа.
Если есть обученная модель, для прогона на стабе укажите несуществующий
`[layout].checkpoint` в своём `models.toml` и передайте каталог настроек
через `genfacade -c <каталог> serve`. Отчёт попадёт в
`tmp/braille/runs/simple-house/report.json`.

`node braille/upstream/bin/braille.mjs help` показывает команды пошагового режима.
Для `--record-api` и `--replay-api` задайте `BRAILLE_API_ROOTS=/api,/files`,
чтобы записывать также SVG прогона. При воспроизведении сервер отдаёт страницу
и статические файлы, а записанные запросы подменяет раннер. Подробности в
[документации записи](upstream/docs/RECORDINGS.md).

## Обновление

Замените копии upstream на файлы выбранной ревизии и укажите её в [NOTICE](NOTICE).
Соберите скрипт для FastAPI и проверьте исходный runtime.

```sh
npm ci --prefix braille/upstream
sh braille/build.sh
npm --prefix braille/upstream run test:runtime
node braille/upstream/bin/braille.mjs selftest
```
