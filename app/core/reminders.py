"""Движок напоминаний по сделкам.

Сканирует активные сделки и формирует короткие actionable-напоминания:
не написал продавцу, продавец не ответил, куплено но не выставлено, висит
дольше прогноза → снизь цену. Чтобы не спамить — одно напоминание на сделку
не чаще раза в ~20 часов.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import Deal, DealStatus

logger = logging.getLogger(__name__)

_THROTTLE = timedelta(hours=20)


@dataclass
class Reminder:
    deal_id: int
    text: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age(dt: datetime | None) -> timedelta | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return _now() - dt


def _build_reminder(deal: Deal) -> str | None:
    """Возвращает текст напоминания для сделки или None, если ничего не нужно."""
    st = deal.status

    if st == DealStatus.new and deal.verdict and deal.verdict.value in {"BUY_NOW", "NEGOTIATE"}:
        age = _age(deal.created_at)
        if age and age > timedelta(hours=2):
            return (f"⏰ Выгодный лот «{deal.title}» висит у тебя {int(age.total_seconds()//3600)} ч, "
                    f"а продавцу ещё не написал. Чистая прибыль ~{deal.expected_profit}₽ — не упусти.")

    if st == DealStatus.contacted and not deal.seller_replied:
        age = _age(deal.updated_at)
        if age and age > timedelta(hours=24):
            return (f"📭 По «{deal.title}» продавец молчит больше суток. "
                    f"Напомни о себе или переходи к следующему варианту.")

    if st == DealStatus.bought and deal.listed_at is None:
        age = _age(deal.bought_at)
        if age and age > timedelta(days=2):
            return (f"📦 «{deal.title}» куплено {age.days} дн. назад, но ещё не выставлено. "
                    f"Капитал заморожен — сделай черновик перепродажи и выстави.")

    if st == DealStatus.listed and deal.listed_at is not None:
        age = _age(deal.listed_at)
        target_days = (deal.days_to_sell_est or 7) * 1.5
        if age and age.days >= target_days:
            cur = deal.resale_price or deal.quick_sale_price or 0
            new_price = int(cur * 0.95) if cur else None
            tail = f" Снизь цену до ~{new_price}₽ (−5%)." if new_price else " Снизь цену на ~5%."
            return (f"🏷 «{deal.title}» продаётся уже {age.days} дн. (прогноз был "
                    f"~{deal.days_to_sell_est} дн).{tail}")

    return None


async def scan_due(session: AsyncSession) -> list[Reminder]:
    active = [DealStatus.new, DealStatus.contacted, DealStatus.bought, DealStatus.listed]
    res = await session.execute(select(Deal).where(Deal.status.in_(active)))
    deals = list(res.scalars().all())

    out: list[Reminder] = []
    for deal in deals:
        last = _age(deal.last_reminded_at)
        if last is not None and last < _THROTTLE:
            continue
        text = _build_reminder(deal)
        if text:
            deal.last_reminded_at = _now()
            deal.reminder_count += 1
            out.append(Reminder(deal_id=deal.id, text=text))
    return out


async def run_reminder_loop(on_reminder, stop_event: asyncio.Event | None = None) -> None:
    """Фоновый цикл: периодически шлёт напоминания через колбэк on_reminder(deal_id, text)."""
    interval = max(5, settings.reminder_scan_min) * 60
    stop = stop_event or asyncio.Event()
    logger.info("Напоминания запущены (раз в %s мин)", settings.reminder_scan_min)
    while not stop.is_set():
        try:
            async with get_session() as session:
                due = await scan_due(session)
            for r in due:
                try:
                    await on_reminder(r.deal_id, r.text)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Не удалось отправить напоминание: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка в цикле напоминаний: %s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
