"""Тесты автоопределения публичного URL дашборда (Mini App)."""
from __future__ import annotations

from app.config import Settings


def test_explicit_webapp_url_wins(monkeypatch):
    monkeypatch.delenv("REPLIT_DEV_DOMAIN", raising=False)
    s = Settings(WEBAPP_URL="https://my.example.com/")
    assert s.webapp_url == "https://my.example.com"  # trailing slash убран


def test_replit_dev_domain_autodetected(monkeypatch):
    monkeypatch.setenv("REPLIT_DEV_DOMAIN", "abc-00-xyz.replit.dev")
    s = Settings(WEBAPP_URL="")
    assert s.webapp_url == "https://abc-00-xyz.replit.dev"


def test_replit_domains_fallback(monkeypatch):
    monkeypatch.delenv("REPLIT_DEV_DOMAIN", raising=False)
    monkeypatch.setenv("REPLIT_DOMAINS", "first.replit.app,second.replit.app")
    s = Settings(WEBAPP_URL="")
    assert s.webapp_url == "https://first.replit.app"


def test_no_url_when_nothing_set(monkeypatch):
    monkeypatch.delenv("REPLIT_DEV_DOMAIN", raising=False)
    monkeypatch.delenv("REPLIT_DOMAINS", raising=False)
    s = Settings(WEBAPP_URL="")
    assert s.webapp_url == ""
