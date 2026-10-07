#!/usr/bin/env python3
"""Telegram → буфер входящих (gf#82).

    python3 tools/tg_inbox.py pull --buffer ПАПКА        новое из темы «Входящие» → буфер
    python3 tools/tg_inbox.py discover                   id групп, номера тем, id отправителей
    python3 tools/tg_inbox.py send --topic T --file F    текст файла в тему; --thread N — проба
    python3 tools/tg_inbox.py --selftest

Хозяин пересылает пачку сообщений из чата научруков в тему «Входящие» своей группы. `pull`
берёт из `getUpdates` только сообщения этой группы, этой темы и от хозяина, отсекает уже
виденное, дописывает новое в `ПАПКА/messages.jsonl` и отвечает в теме «принял N, новых M,
повторов K». Буфер — ветка `tg-inbox`; пишет его только Action `tg-pull.yml` (по расписанию
и вручную из `/inbox`), чтобы у буфера был один писатель.

Почему отсев своим ключом: повторную доставку Telegram отсекает сам (`offset`), но пачка,
пересланная второй раз, — это новые сообщения бота. Исходного `message_id` у пересылки от
человека Bot API не отдаёт, поэтому ключ — исходный автор, исходная дата, текст и
`file_unique_id` вложений.

Почему последняя страница не подтверждается: апдейт подтверждается вызовом `getUpdates`
с бо́льшим `offset`. Подтверди сразу — и если коммит буфера сорвётся, сообщения пропадут;
`offset` хранится в `state.json` и подтверждает их следующим сбором, уже после коммита.

Адрес — переменные окружения или `.env`: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
TELEGRAM_OWNER_ID, TELEGRAM_THREAD_{INBOX,ANALYSIS,QUESTIONS,TASKS,RESULTS};
TELEGRAM_API_BASE — подставной сервер для проверки. Без токена — предупреждение и выход 0:
тот же скрипт запускают CI и машины, где бота нет.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import http.server
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from script_common import report, run_script

API_BASE = "https://api.telegram.org"
# Паузы между повторами при обрыве, 429 и 5xx — как в telegram-send dgtlU; 429 со своим
# `retry_after` ждёт столько, сколько попросил Telegram.
RETRY_PAUSES = (5, 15, 40)
TIMEOUT = 30
PAGE = 100  # больше getUpdates за вызов не отдаёт
# Поля сообщения Bot API, в которых приходит файл.
MEDIA_FIELDS = ("document", "photo", "video", "audio", "voice", "animation", "video_note")
MESSAGES = "messages.jsonl"
STATE = "state.json"


class Topic(StrEnum):
    """Темы группы; номер темы — в переменной TELEGRAM_THREAD_<ИМЯ>."""

    INBOX = "inbox"
    ANALYSIS = "analysis"
    QUESTIONS = "questions"
    TASKS = "tasks"
    RESULTS = "results"

    @property
    def env(self) -> str:
        return f"TELEGRAM_THREAD_{self.name}"


class Origin(StrEnum):
    """`MessageOrigin.type` Bot API: откуда переслано сообщение."""

    USER = "user"
    HIDDEN_USER = "hidden_user"
    CHAT = "chat"
    CHANNEL = "channel"


class TelegramError(Exception):
    def __init__(self, code: int, description: str, retry_after: int | None = None):
        super().__init__(f"{code}: {description}")
        self.code = code
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.code == 429 or self.code >= 500


@dataclasses.dataclass(frozen=True)
class Config:
    token: str
    chat_id: int | None = None
    owner_id: int | None = None
    threads: dict[Topic, int] = dataclasses.field(default_factory=dict)
    base: str = API_BASE
    pauses: tuple[float, ...] = RETRY_PAUSES


def dotenv(path: Path) -> dict[str, str]:
    """`.env` — строки КЛЮЧ=значение; комментарии и пустые строки пропускаются."""
    if not path.exists():
        return {}
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
             if "=" in line and not line.lstrip().startswith("#"))
    return {key.strip(): value.strip().strip("'\"") for key, value in pairs}


def number(env: dict[str, str], key: str) -> int | None:
    return int(env[key]) if env.get(key) else None


def load_config(env: dict[str, str]) -> Config | None:
    if not env.get("TELEGRAM_BOT_TOKEN"):
        return None
    threads = {topic: number(env, topic.env) for topic in Topic if env.get(topic.env)}
    base = env.get("TELEGRAM_API_BASE") or API_BASE
    if urllib.parse.urlsplit(base).scheme not in ("http", "https"):
        raise ValueError(f"TELEGRAM_API_BASE: ожидался http(s), а не {base}")
    return Config(env["TELEGRAM_BOT_TOKEN"], number(env, "TELEGRAM_CHAT_ID"),
                  number(env, "TELEGRAM_OWNER_ID"), threads, base)


# ---------------------------------------------------------------------------
# Bot API
# ---------------------------------------------------------------------------


def call(cfg: Config, method: str, params: dict) -> object:
    # схема адреса проверена в load_config: только http(s)
    request = urllib.request.Request(f"{cfg.base}/bot{cfg.token}/{method}",  # noqa: S310
                                     json.dumps(params).encode(),
                                     {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            body = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            body = json.load(error)
        except ValueError:
            raise TelegramError(error.code, str(error.reason)) from error
    if not body.get("ok"):
        retry_after = body.get("parameters", {}).get("retry_after")
        raise TelegramError(body.get("error_code", 0), body.get("description", ""), retry_after)
    return body["result"]


def call_with_retries(cfg: Config, method: str, params: dict) -> object:
    """Обрыв, 429 и 5xx — повтор; отказ вроде «chat not found» — сразу наверх."""
    for pause in (*cfg.pauses, None):
        try:
            return call(cfg, method, params)
        except TelegramError as error:
            if not error.retryable or pause is None:
                raise
            wait, reason = error.retry_after or pause, error
        except OSError as error:
            if pause is None:
                raise
            wait, reason = pause, error
        print(f"повтор через {wait} с: {reason}", file=sys.stderr)
        time.sleep(wait)
    raise AssertionError("цикл повторов кончается return или raise")


def send(cfg: Config, thread: int | None, text: str) -> None:
    call_with_retries(cfg, "sendMessage",
                      {"chat_id": cfg.chat_id, "message_thread_id": thread, "text": text})


# ---------------------------------------------------------------------------
# Сообщение → запись буфера
# ---------------------------------------------------------------------------


def person(user: dict) -> str:
    name = " ".join(filter(None, (user.get("first_name"), user.get("last_name"))))
    return f"{name} (@{user['username']})" if user.get("username") else name


def author(message: dict) -> tuple[str, str]:
    """Исходный автор: ключ для отсева и имя для человека."""
    origin = message.get("forward_origin")
    if origin is None:
        return f"user:{message['from']['id']}", person(message["from"])
    kind = Origin(origin["type"])
    if kind is Origin.USER:
        return f"user:{origin['sender_user']['id']}", person(origin["sender_user"])
    if kind is Origin.HIDDEN_USER:
        return f"hidden:{origin['sender_user_name']}", origin["sender_user_name"]
    chat = origin["chat"] if kind is Origin.CHANNEL else origin["sender_chat"]
    # у пересылки из канала исходный номер есть — он и различает сообщения
    suffix = f":{origin['message_id']}" if kind is Origin.CHANNEL else ""
    return f"{kind}:{chat['id']}{suffix}", chat.get("title", "")


def attachments(message: dict) -> list[dict]:
    found = []
    for name in MEDIA_FIELDS:
        media = message.get(name)
        if isinstance(media, list):  # фото приходит набором размеров — берём крупнейший
            media = max(media, key=lambda size: size.get("width", 0) * size.get("height", 0))
        if media:
            found.append({"kind": name, "file_id": media["file_id"],
                          "file_unique_id": media["file_unique_id"],
                          "name": media.get("file_name", ""), "size": media.get("file_size")})
    return found


def iso(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()


def body(message: dict) -> str:
    return message.get("text") or message.get("caption") or ""


def reply_context(message: dict) -> dict | None:
    """На что ответ. Пересланный ответ Telegram пересылает вместе с исходным сообщением и
    кладёт его в `reply_to_message`; каждое сообщение темы ещё и «отвечает» на её корень —
    это не контекст, у корня нет `forward_origin`."""
    parent = message.get("reply_to_message")
    if not parent or "forward_origin" not in parent:
        return None
    return {"author": author(parent)[1], "date": iso(parent["forward_origin"]["date"]),
            "text": body(parent)}


def to_record(message: dict) -> dict:
    """Ключ отсева — без `reply_to`: ответ, пересланный сам по себе и вместе с исходным, —
    одно и то же сообщение."""
    files = attachments(message)
    text = body(message)
    entities = message.get("entities") or message.get("caption_entities") or []
    key_author, name = author(message)
    date = message.get("forward_origin", message)["date"]
    source = "\n".join([key_author, str(date), text, *(f["file_unique_id"] for f in files)])
    return {"key": hashlib.sha256(source.encode()).hexdigest(), "author": name,
            "date": iso(date), "forwarded": "forward_origin" in message, "text": text,
            "links": [entity["url"] for entity in entities if entity.get("url")],
            "reply_to": reply_context(message), "files": files, "received": iso(message["date"])}


def from_inbox(update: dict, cfg: Config) -> dict | None:
    """Сообщение хозяина в теме «Входящие» его группы; всё остальное молча мимо."""
    message = update.get("message")
    if not message or message["chat"]["id"] != cfg.chat_id:
        return None
    if message.get("message_thread_id") != cfg.threads.get(Topic.INBOX):
        return None
    if message.get("from", {}).get("id") != cfg.owner_id:
        return None
    return message if body(message) or attachments(message) else None


# ---------------------------------------------------------------------------
# Буфер и сбор
# ---------------------------------------------------------------------------


def load_buffer(folder: Path) -> tuple[int | None, set[str]]:
    state = folder / STATE
    offset = json.loads(state.read_text(encoding="utf-8"))["offset"] if state.exists() else None
    messages = folder / MESSAGES
    lines = messages.read_text(encoding="utf-8").splitlines() if messages.exists() else []
    return offset, {json.loads(line)["key"] for line in lines}


def save_buffer(folder: Path, offset: int | None, records: list[dict]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / MESSAGES).open("a", encoding="utf-8") as out:
        out.writelines(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
    (folder / STATE).write_text(json.dumps({"offset": offset}) + "\n", encoding="utf-8")


def fetch_updates(cfg: Config, offset: int | None) -> tuple[list[dict], int | None]:
    """Все неподтверждённые апдейты; последняя неполная страница остаётся неподтверждённой."""
    updates: list[dict] = []
    while True:
        page = call_with_retries(cfg, "getUpdates", {"offset": offset, "limit": PAGE,
                                                     "timeout": 0, "allowed_updates": ["message"]})
        updates += page
        if page:
            offset = page[-1]["update_id"] + 1
        if len(page) < PAGE:
            return updates, offset


def pull(cfg: Config, folder: Path) -> tuple[int, int]:
    """Новое из «Входящих» — в буфер; возвращает (принято, новых)."""
    offset, seen = load_buffer(folder)
    updates, offset = fetch_updates(cfg, offset)
    taken = [to_record(m) for m in (from_inbox(u, cfg) for u in updates) if m]
    fresh = []
    for record in taken:
        if record["key"] not in seen:
            seen.add(record["key"])
            fresh.append(record)
    save_buffer(folder, offset, fresh)
    if taken:
        repeats = len(taken) - len(fresh)
        send(cfg, cfg.threads[Topic.INBOX],
             f"принял {len(taken)}, новых {len(fresh)}, повторов {repeats}")
    return len(taken), len(fresh)


def discover(cfg: Config) -> list[str]:
    """Без `offset` getUpdates ничего не подтверждает — пробу можно гонять сколько угодно."""
    lines = []
    for update in call(cfg, "getUpdates", {"timeout": 0, "limit": PAGE}):
        message = update.get("message") or {}
        if not message:
            continue
        chat, sender = message["chat"], message.get("from", {})
        lines.append(f"чат {chat['id']} «{chat.get('title', '')}» · тема "
                     f"{message.get('message_thread_id', '—')} · от {sender.get('id')} "
                     f"{person(sender)} · {(message.get('text') or '')[:40]}")
    return list(dict.fromkeys(lines))


# ---------------------------------------------------------------------------
# Командная строка
# ---------------------------------------------------------------------------


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Telegram → буфер входящих (gf#82)")
    commands = cli.add_subparsers(dest="command", required=True)
    commands.add_parser("pull").add_argument("--buffer", type=Path, required=True)
    commands.add_parser("discover")
    sender = commands.add_parser("send")
    sender.add_argument("--file", type=Path, required=True)
    where = sender.add_mutually_exclusive_group(required=True)
    where.add_argument("--topic", type=Topic, choices=list(Topic))
    where.add_argument("--thread", type=int)
    return cli


def missing(cfg: Config, args: argparse.Namespace) -> list[str]:
    need = {"TELEGRAM_CHAT_ID": cfg.chat_id}
    if args.command == "pull":
        need |= {"TELEGRAM_OWNER_ID": cfg.owner_id, Topic.INBOX.env: cfg.threads.get(Topic.INBOX)}
    if getattr(args, "topic", None):
        need[args.topic.env] = cfg.threads.get(args.topic)
    return [] if args.command == "discover" else [k for k, v in need.items() if v is None]


def execute(cfg: Config, args: argparse.Namespace) -> None:
    if args.command == "pull":
        taken, fresh = pull(cfg, args.buffer)
        print(f"принято {taken}, новых {fresh} → {args.buffer / MESSAGES}")
    elif args.command == "discover":
        print("\n".join(discover(cfg)) or "апдейтов нет: напишите в каждую тему и повторите")
    else:
        thread = cfg.threads[args.topic] if args.topic else args.thread
        send(cfg, thread, args.file.read_text(encoding="utf-8"))
        print("отправлено")


def cli(argv: list[str], env: dict[str, str]) -> int:
    args = parser().parse_args(argv)
    cfg = load_config(env)
    if cfg is None:
        print("предупреждение: нет TELEGRAM_BOT_TOKEN — ничего не делаю", file=sys.stderr)
        return 0
    if gaps := missing(cfg, args):
        print("не заданы: " + ", ".join(gaps), file=sys.stderr)
        return 1
    try:
        execute(cfg, args)
    except TelegramError as error:
        print(f"Telegram отказал: {error}", file=sys.stderr)
        return 1
    return 0


def run(root: Path) -> int:
    return cli(sys.argv[1:], {**dotenv(root / ".env"), **os.environ})


# ---------------------------------------------------------------------------
# selftest: подставной Telegram на 127.0.0.1 — отсев, фильтр, offset, повторы, без токена
# ---------------------------------------------------------------------------

OWNER, CHAT, INBOX, OTHER_THREAD, STRANGER = 7, -100500, 11, 12, 8


class FakeTelegram:
    """Держит апдейты как Telegram: `offset` подтверждает и выбрасывает те, что младше."""

    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.sent: list[dict] = []
        self.calls: list[str] = []
        self.failures: list[tuple[int, dict]] = []  # отдать по очереди до ответа по существу

    def answer(self, method: str, params: dict) -> tuple[int, dict]:
        self.calls.append(method)
        if self.failures:
            return self.failures.pop(0)
        if method == "getUpdates":
            if params.get("offset") is not None:
                self.updates = [u for u in self.updates if u["update_id"] >= params["offset"]]
            return 200, {"ok": True, "result": self.updates[:params.get("limit", PAGE)]}
        if params.get("message_thread_id") not in (INBOX, OTHER_THREAD):
            return 400, {"ok": False, "error_code": 400, "description": "message thread not found"}
        self.sent.append(params)
        return 200, {"ok": True, "result": {}}

    def serve(self) -> http.server.ThreadingHTTPServer:
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # имя метода задаёт http.server
                params = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                status, body = fake.answer(self.path.rsplit("/", 1)[-1], params)
                self.send_response(status)
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def log_message(self, *args: object) -> None:
                """Тише: журнал запросов самопроверке не нужен."""

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server


def message(text: str, origin: dict | None = None, **where: int) -> dict:
    """Сообщение в «Входящих» от хозяина; `where` переопределяет чат, тему, отправителя."""
    fields = {"message_id": len(text), "date": 1_800_000_000, "text": text,
            "chat": {"id": where.get("chat", CHAT)}, "from": {"id": where.get("sender", OWNER),
                                                             "first_name": "Никон"},
            "message_thread_id": where.get("thread", INBOX),
            # каждое сообщение темы отвечает на её корень — сборщик не должен счесть это контекстом
            "reply_to_message": {"message_id": INBOX, "forum_topic_created": {"name": "Входящие"}}}
    return fields | ({"forward_origin": origin} if origin else {})


def from_user(user_id: int, date: int) -> dict:
    return {"type": "user", "date": date, "sender_user": {"id": user_id, "first_name": "Егор"}}


def first_batch() -> list[dict]:
    hidden = {"type": "hidden_user", "date": 1_700_000_100, "sender_user_name": "Валерия"}
    plan = message("план готов", from_user(1, 1_700_000_000))
    return [plan, message("окна по сетке", hidden) | {"reply_to_message": plan},
            message("", from_user(1, 1_700_000_200)) | {
                "caption": "чертёж", "document": {"file_id": "F1", "file_unique_id": "U1",
                                                   "file_name": "a.pdf", "file_size": 10}}]


def second_batch() -> list[dict]:
    """Два повтора первой пачки, три новых и три чужих: не та тема, не тот чат, не хозяин."""
    old = first_batch()
    return [old[1], old[2],
            message("план готов", from_user(2, 1_700_000_000)),  # тот же текст, другой автор
            message("план готов", from_user(1, 1_700_000_300)),  # тот же автор, другая дата
            message("сам добавил"),
            message("мимо", thread=OTHER_THREAD), message("мимо", chat=1),
            message("мимо", sender=STRANGER)]


def as_updates(fake: FakeTelegram, messages: list[dict]) -> None:
    start = fake.updates[-1]["update_id"] + 1 if fake.updates else 100
    fake.updates += [{"update_id": start + i, "message": m} for i, m in enumerate(messages)]


def check_pull(cfg: Config, fake: FakeTelegram, folder: Path) -> list[str]:
    bad = []
    as_updates(fake, first_batch())
    expected = [((3, 3), "принял 3, новых 3, повторов 0"),
                ((5, 3), "принял 5, новых 3, повторов 2")]
    for batch, ((taken, fresh), reply) in enumerate(expected):
        if batch:
            as_updates(fake, second_batch())
        if (got := pull(cfg, folder)) != (taken, fresh):
            bad.append(f"пачка {batch + 1}: (принято, новых) = {got}, ждали {(taken, fresh)}")
        if fake.sent[-1:] != [{"chat_id": CHAT, "message_thread_id": INBOX, "text": reply}]:
            bad.append(f"пачка {batch + 1}: ответ {fake.sent[-1:]}, ждали «{reply}»")
    lines = (folder / MESSAGES).read_text(encoding="utf-8").splitlines()
    files = [r["files"] for r in map(json.loads, lines) if r["files"]]
    if len(lines) != 6 or files != [[{"kind": "document", "file_id": "F1", "file_unique_id": "U1",
                                      "name": "a.pdf", "size": 10}]]:
        bad.append(f"в буфере {len(lines)} строк, вложения {files}; ждали 6 и один a.pdf")
    replies = [r["reply_to"] for r in map(json.loads, lines) if r["reply_to"]]
    if replies != [{"author": "Егор", "date": iso(1_700_000_000), "text": "план готов"}]:
        bad.append(f"контекст ответа: {replies}; ждали один — на «план готов» Егора")
    sent_before = len(fake.sent)
    if pull(cfg, folder) != (0, 0) or len(fake.sent) != sent_before:
        bad.append("третий сбор без новых апдейтов должен молчать")
    return bad


def check_retries(cfg: Config, fake: FakeTelegram) -> list[str]:
    bad = []
    flood = {"ok": False, "error_code": 429, "description": "Too Many Requests",
             "parameters": {"retry_after": 0}}
    fake.failures = [(429, flood), (502, {"ok": False, "error_code": 502, "description": "x"})]
    before = len(fake.calls)
    try:
        send(cfg, INBOX, "проба")
    except TelegramError as error:
        bad.append(f"429 и 502 должны повторяться, а дошло до отказа: {error}")
    if len(fake.calls) - before != 3:
        bad.append(f"429 и 502 → повторы и успех: вызовов {len(fake.calls) - before}, ждали 3")
    fake.failures = []  # недоеденные отказы не должны перетечь в следующую проверку
    before = len(fake.calls)
    try:
        send(cfg, 999_999, "проба")
        bad.append("тема 999999 должна дать 400")
    except TelegramError as error:
        if error.code != 400 or len(fake.calls) - before != 1:
            bad.append(f"400 без повторов: код {error.code}, вызовов {len(fake.calls) - before}")
    return bad


def selftest() -> int:
    fake = FakeTelegram()
    server = fake.serve()
    env = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": str(CHAT),
           "TELEGRAM_OWNER_ID": str(OWNER), Topic.INBOX.env: str(INBOX),
           "TELEGRAM_API_BASE": f"http://127.0.0.1:{server.server_port}"}
    cfg = dataclasses.replace(load_config(env), pauses=(0, 0, 0))
    with tempfile.TemporaryDirectory() as tmp:
        bad = check_pull(cfg, fake, Path(tmp) / "inbox")
        bad += check_retries(cfg, fake)
        if cli(["pull", "--buffer", tmp], {}) != 0:
            bad.append("без токена pull должен выйти с кодом 0")
    server.shutdown()
    return report(bad, "отсев повторов и чужих, offset, ответ в теме, повторы 429/5xx, "
                       "400 без повтора, без токена — выход 0")


if __name__ == "__main__":
    sys.exit(run_script(selftest, run))
