# Braille в смотрелке Gen Facade

Braille возвращает доступные элементы, запросы и ошибки смотрелки в JSON. Раннер и
браузерный скрипт перенесены из Welta, ревизия `3b60b5a`. Сведения об исходном
agent-braille и лицензия Apache-2.0 находятся в [NOTICE](NOTICE) и [LICENSE](LICENSE).

## Запуск

В окружении Gen Facade установите зависимости смотрелки и браузера.

```sh
python3 -m pip install -e '.[viewer,braille]'
python3 -m playwright install chromium
AGENT_API=1 genfacade serve
```

Флаг читается при запуске сервера. Главная страница подключает `/braille/agent.js`
перед кодом смотрелки. Браузер получает `window.__agent` с методами `screen()`,
`find()`, `busy()`, `visual()` и `errors()`. Обычный запуск смотрелки без флага
отвечает 404 на запрос скрипта.

## Прогон через браузер

Из корня проекта выполните сценарий на чистой локальной смотрелке. Файл
[braille-viewer-steps.json](../tests/fixtures/braille-viewer-steps.json) открывает
форму нового дома, выбирает `simple_house`, запускает генерацию и открывает лист.
Если в рабочем окружении есть обученная модель, для прогона на стабе укажите
несуществующий путь `[layout].checkpoint` в своём `models.toml` и передайте каталог
настроек через `genfacade -c <каталог> serve`.

```sh
set -e
session=$(mktemp -d)
python3 -m braille start --base http://127.0.0.1:8000 --session "$session"
jq -c '.[]' tests/fixtures/braille-viewer-steps.json | while IFS= read -r step; do
    python3 -m braille step "$step" --session "$session" || exit 1
done
python3 -m braille look --screenshot --session "$session"
python3 -m braille close --session "$session"
```

Успешные шаги записываются в `steps.json`. `look --screenshot` возвращает наблюдение
и путь к `out/look.png`. Красный шаг возвращает причину и сохраняет свои улики.
По умолчанию разрешены только `localhost` и `127.0.0.1`. Настройки раннера находятся
в [braille.json](braille.json). Контроль без браузера и сети — `python3 -m braille selftest`.
