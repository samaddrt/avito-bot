"""Тесты проверки Telegram WebApp initData (HMAC) и доступа владельца."""
from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlencode

from app.config import settings
from app.web import security

TOKEN = "12345:TEST_TOKEN"
OWNER_ID = 777


def make_init_data(user_id: int, token: str = TOKEN) -> str:
    fields = {"user": json.dumps({"id": user_id, "first_name": "T"}), "auth_date": "1700000000"}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def _set_owner(monkeypatch):
    monkeypatch.setattr(settings, "bot_token", TOKEN)
    monkeypatch.setattr(settings, "owner_telegram_id", OWNER_ID)


def test_valid_init_data_accepted(monkeypatch):
    _set_owner(monkeypatch)
    user = security.validate_init_data(make_init_data(OWNER_ID))
    assert user and user["id"] == OWNER_ID


def test_tampered_hash_rejected(monkeypatch):
    _set_owner(monkeypatch)
    bad = make_init_data(OWNER_ID, token="999:OTHER_TOKEN")
    assert security.validate_init_data(bad) is None


def test_owner_request_checks_user_id(monkeypatch):
    _set_owner(monkeypatch)
    assert security.is_owner_request(make_init_data(OWNER_ID), "1.2.3.4") is True
    # Валидная подпись, но чужой id — отказ.
    assert security.is_owner_request(make_init_data(OWNER_ID + 1), "1.2.3.4") is False


def test_dev_mode_localhost_only(monkeypatch):
    _set_owner(monkeypatch)
    assert security.is_owner_request(None, "127.0.0.1") is True
    assert security.is_owner_request(None, "8.8.8.8") is False
