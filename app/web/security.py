"""Проверка Telegram WebApp initData (HMAC) и доступа владельца."""
from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from app.config import settings


def validate_init_data(init_data: str) -> dict | None:
    """Проверяет подпись initData по алгоритму Telegram. Возвращает user-объект или None."""
    if not init_data or not settings.bot_token:
        return None
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None

    user_raw = parsed.get("user")
    if not user_raw:
        return None
    try:
        return json.loads(user_raw)
    except json.JSONDecodeError:
        return None


def is_owner_request(init_data: str | None, client_host: str | None) -> bool:
    """Доступ разрешён, если: валидный initData владельца ИЛИ локальный dev-запрос."""
    if init_data:
        user = validate_init_data(init_data)
        if user and int(user.get("id", 0)) == settings.owner_telegram_id:
            return True
        return False
    # Dev-режим: без initData пускаем только с localhost.
    return client_host in {"127.0.0.1", "localhost", "::1"}
