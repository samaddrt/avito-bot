"""Тесты правил напоминаний (_build_reminder — чистая функция от сделки)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.reminders import _build_reminder
from app.models import Deal, DealStatus, Verdict


def _ago(**kwargs) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**kwargs)


def make_deal(**attrs) -> Deal:
    d = Deal()
    d.title = attrs.pop("title", "PS5 Slim")
    d.status = attrs.pop("status", DealStatus.new)
    for k, v in attrs.items():
        setattr(d, k, v)
    return d


def test_hot_deal_not_contacted():
    d = make_deal(verdict=Verdict.BUY_NOW, created_at=_ago(hours=3), expected_profit=8000)
    text = _build_reminder(d)
    assert text and "не упусти" in text


def test_fresh_deal_no_reminder():
    d = make_deal(verdict=Verdict.BUY_NOW, created_at=_ago(minutes=30), expected_profit=8000)
    assert _build_reminder(d) is None


def test_skip_verdict_no_reminder():
    d = make_deal(verdict=Verdict.SKIP, created_at=_ago(hours=10))
    assert _build_reminder(d) is None


def test_seller_silent_over_a_day():
    d = make_deal(status=DealStatus.contacted, seller_replied=False, updated_at=_ago(hours=30))
    assert "молчит" in _build_reminder(d)


def test_seller_replied_no_reminder():
    d = make_deal(status=DealStatus.contacted, seller_replied=True, updated_at=_ago(hours=30))
    assert _build_reminder(d) is None


def test_bought_but_not_listed():
    d = make_deal(status=DealStatus.bought, bought_at=_ago(days=3), listed_at=None)
    assert "не выставлено" in _build_reminder(d)


def test_listed_too_long_suggests_price_drop():
    d = make_deal(status=DealStatus.listed, listed_at=_ago(days=15),
                  days_to_sell_est=7, resale_price=36000)
    text = _build_reminder(d)
    assert text and "Снизь цену" in text and str(int(36000 * 0.95)) in text


def test_listed_within_estimate_no_reminder():
    d = make_deal(status=DealStatus.listed, listed_at=_ago(days=2), days_to_sell_est=7)
    assert _build_reminder(d) is None
