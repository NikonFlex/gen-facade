"""Подключение наблюдения к локальной смотрелке при AGENT_API=1."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # fastapi нужен только сайтам: `python3 -m braille` идёт и без него
    from fastapi import FastAPI

#: переменная окружения, включающая объект (значение "1")
ENV_FLAG = "AGENT_API"
#: Скрипт нужен до первого запроса страницы, чтобы увидеть её fetch.
SCRIPT_URL = "/braille/agent.js"
SCRIPT = Path(__file__).resolve().parent / "agent.js"
#: скрипт правят вместе с кодом, поэтому браузер перепроверяет его при каждой загрузке
NO_CACHE = {"Cache-Control": "no-cache"}


def enabled() -> bool:
    return os.environ.get(ENV_FLAG) == "1"


def install(app: FastAPI) -> bool:
    """Зарегистрировать скрипт только для этого экземпляра смотрелки."""
    on = enabled()
    if on:
        app.add_api_route(SCRIPT_URL, script, methods=["GET"], include_in_schema=False)
    return on


def script():  # без аннотации: FastAPI не должен искать FileResponse в этом модуле
    from fastapi.responses import FileResponse

    return FileResponse(SCRIPT, media_type="text/javascript", headers=NO_CACHE)
