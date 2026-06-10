"""Цикл мониторинга Avito.

Аккуратно (раз в 3-5 мин со случайным джиттером, поиски по очереди) собирает
новые объявления, прогоняет через анализ и пушит в Telegram только годные
варианты. При капче/блокировке — пауза с экспоненциальным бэкоффом и уведомление.
"""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from app.ai.analyzer import analyze_listing
from app.config import settings
from app.core import deals as deals_service
from app.core.sources import CaptchaError, RawListing
from app.db import get_session, get_watcher_state, listing_exists
from app.models import Deal
from app.watcher import avito, searches

logger = logging.getLogger(__name__)

# Лесенка бэкоффа при блокировках.
_BACKOFF_STEPS = [15 * 60, 60 * 60, 4 * 60 * 60]  # 15 мин, 1 ч, 4 ч

# Вердикты, которые заслуживают пуша в Telegram.
_PUSH_VERDICTS = {"BUY_NOW", "NEGOTIATE"}

# Тип колбэков, которые подставляет run.py (связь с ботом).
DealPush = Callable[[int], Awaitable[None]]
Alert = Callable[[str], Awaitable[None]]


class Monitor:
    def __init__(self, on_deal: DealPush | None = None, on_alert: Alert | None = None):
        self.on_deal = on_deal
        self.on_alert = on_alert
        self._stop = asyncio.Event()
        self._detail_budget = 0  # выставляется в начале каждого прохода
        self._last_error_alert: datetime | None = None  # троттлинг алертов об ошибках

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if not settings.watcher_enabled:
            logger.info("Watcher выключен (WATCHER_ENABLED=0)")
            return
        logger.info("Watcher запущен")
        await self._announce_start()
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Ошибка в цикле мониторинга: %s", exc)
                await self._record_error(str(exc))
                await self._alert_error(exc)
            # Пауза до следующего прохода (с джиттером).
            delay = random.randint(settings.watch_interval_min, settings.watch_interval_max)
            await self._sleep_or_stop(delay)

    async def _announce_start(self) -> None:
        """Шлёт владельцу короткое резюме при старте, чтобы было видно состояние мониторинга."""
        if not self.on_alert:
            return
        active = searches.enabled_searches()
        if active:
            msg = (
                f"▶️ Мониторинг запущен. Активных поисков: {len(active)}.\n"
                "Пришлю варианты с вердиктом «брать» или «торговаться»."
            )
        else:
            msg = (
                "▶️ Мониторинг запущен, но активных поисков нет — поэтому он молчит.\n"
                "Добавь поиск: /addsearch URL_поиска_Avito, либо включи готовые в /searches."
            )
        try:
            await self.on_alert(msg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось отправить стартовое уведомление: %s", exc)

    async def _alert_error(self, exc: Exception) -> None:
        """Уведомляет владельца о сбое мониторинга (не чаще раза в 30 мин), без спама."""
        if not self.on_alert:
            return
        now = datetime.now(timezone.utc)
        if self._last_error_alert and (now - self._last_error_alert) < timedelta(minutes=30):
            return
        self._last_error_alert = now
        text = str(exc)
        if "executable" in text.lower() or "playwright install" in text.lower():
            hint = (
                "⚠️ Мониторинг не может запустить браузер: не установлен Chromium для Playwright.\n"
                "Открой Shell в Replit и выполни один раз:\n"
                "<code>playwright install chromium</code>\n"
                "затем перезапусти (Run)."
            )
        else:
            hint = f"⚠️ Сбой мониторинга: {text[:200]}\nПопробую снова в следующем проходе."
        try:
            await self.on_alert(hint)
        except Exception as e:  # noqa: BLE001
            logger.warning("Не удалось отправить алерт об ошибке: %s", e)

    async def _tick(self) -> None:
        # Проверяем паузу/бэкофф.
        async with get_session() as session:
            state = await get_watcher_state(session)
            if state.paused:
                logger.debug("Watcher на паузе: %s", state.paused_reason)
                return
            if state.backoff_until and state.backoff_until > datetime.now(timezone.utc):
                return

        active = searches.enabled_searches()
        if not active:
            logger.debug("Нет активных поисков (включи их в data/searches.json)")
            return

        # Один браузер и один бюджет догрузки описаний на весь проход.
        self._detail_budget = settings.watch_max_detail_per_run
        async with avito.AvitoBrowser() as browser:
            for search in active:
                if self._stop.is_set():
                    return
                try:
                    raw_items = await browser.fetch_search(search)
                except CaptchaError as exc:
                    await self._handle_captcha(str(exc))
                    return
                if not await self._process_items(browser, search, raw_items):
                    return
                # Небольшая человеческая пауза между поисками.
                await self._sleep_or_stop(random.randint(20, 45))

        await self._record_success(len(active))

    async def _process_items(self, browser: "avito.AvitoBrowser", search,
                             raw_items: list[RawListing]) -> bool:
        """Анализирует новые объявления. False — проход надо прервать (капча/стоп)."""
        new_items: list[RawListing] = []
        async with get_session() as session:
            for item in raw_items:
                if not await listing_exists(session, item.avito_id):
                    new_items.append(item)

        if not new_items:
            return True
        logger.info("Поиск '%s': %s новых объявлений", search.name, len(new_items))

        for item in new_items:
            if self._stop.is_set():
                return False
            description = ""
            if self._detail_budget > 0 and item.url:
                try:
                    description = await browser.fetch_detail(item.url)
                    self._detail_budget -= 1
                except CaptchaError as exc:
                    await self._handle_captcha(str(exc))
                    return False
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Не удалось догрузить описание: %s", exc)
            item.description = description
            await self._analyze_and_store(item)
        return True

    async def _analyze_and_store(self, item: RawListing) -> None:
        try:
            result = await analyze_listing(item.combined_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Анализ не удался для %s: %s", item.avito_id, exc)
            return

        async with get_session() as session:
            deal = await deals_service.save_analyzed(
                session, result,
                source="playwright",
                url=item.url,
                avito_id=item.avito_id,
                city=item.city or None,
            )
            verdict = result.scored.verdict
            should_push = verdict in _PUSH_VERDICTS
            if should_push:
                deal.pushed = True
            deal_id = deal.id

        if should_push and self.on_deal:
            try:
                await self.on_deal(deal_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Не удалось отправить пуш по сделке %s: %s", deal_id, exc)

    # --------- Капча / бэкофф ---------
    async def _handle_captcha(self, reason: str) -> None:
        async with get_session() as session:
            state = await get_watcher_state(session)
            level = min(state.backoff_level, len(_BACKOFF_STEPS) - 1)
            wait = _BACKOFF_STEPS[level]
            state.backoff_until = datetime.now(timezone.utc) + timedelta(seconds=wait)
            state.backoff_level = min(state.backoff_level + 1, len(_BACKOFF_STEPS) - 1)
            state.paused_reason = reason
            state.last_error = reason
            await deals_service.log_event(session, "captcha", reason)
        mins = wait // 60
        msg = (
            f"⚠️ Avito показал проверку (капчу).\n{reason}\n\n"
            f"Мониторинг на паузе ~{mins} мин (без обхода защиты). "
            f"Зайди на Avito в своём браузере и пройди проверку вручную, "
            f"затем при необходимости /resume."
        )
        logger.warning(msg)
        if self.on_alert:
            await self.on_alert(msg)

    async def _record_success(self, searches_count: int) -> None:
        async with get_session() as session:
            state = await get_watcher_state(session)
            state.last_run_at = datetime.now(timezone.utc)
            state.runs_total += 1
            state.backoff_level = 0  # успех сбрасывает лесенку
            state.last_error = None

    async def _record_error(self, error: str) -> None:
        async with get_session() as session:
            state = await get_watcher_state(session)
            state.last_error = error

    async def _sleep_or_stop(self, seconds: int) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass


# --------- Управление состоянием (используется ботом) ---------
async def pause(reason: str = "Пауза вручную") -> None:
    async with get_session() as session:
        state = await get_watcher_state(session)
        state.paused = True
        state.paused_reason = reason


async def resume() -> None:
    async with get_session() as session:
        state = await get_watcher_state(session)
        state.paused = False
        state.paused_reason = None
        state.backoff_until = None
        state.backoff_level = 0


async def status_text() -> str:
    async with get_session() as session:
        state = await get_watcher_state(session)
        active = searches.enabled_searches()
        lines = [
            f"Статус: {'⏸ пауза' if state.paused else '▶️ работает'}",
            f"Активных поисков: {len(active)}",
            f"Проходов всего: {state.runs_total}",
        ]
        if state.paused_reason:
            lines.append(f"Причина паузы: {state.paused_reason}")
        if state.backoff_until and state.backoff_until > datetime.now(timezone.utc):
            left = int((state.backoff_until - datetime.now(timezone.utc)).total_seconds() // 60)
            lines.append(f"Бэкофф ещё ~{left} мин")
        if state.last_run_at:
            lines.append(f"Последний проход: {state.last_run_at:%Y-%m-%d %H:%M} UTC")
        if state.last_error:
            lines.append(f"Последняя ошибка: {state.last_error[:120]}")
        return "\n".join(lines)
