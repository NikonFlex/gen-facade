# tg-inbox — буфер переписки из Telegram

Служебная ветка, в `main` не сливается. Пишет её только Action `tg-pull`
(`.github/workflows/tg-pull.yml` в `main`), руками не править.

- `messages.jsonl` — по строке на сообщение из темы «Входящие»: исходный автор и дата,
  текст, ссылки, вложения (`file_id`, без самих файлов);
- `state.json` — `offset` для `getUpdates`.

Устройство — `tools/tg_inbox.py` в `main`, задача gf#82; разбор — `/inbox`, gf#83.
