"""Сборка бота: Bot, Dispatcher и колбэки для пушей вотчера."""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.bot import formatting, keyboards
from app.bot.handlers import router
from app.config import settings
from app.core import deals as deals_service
from app.db import get_session

logger = logging.getLogger(__name__)

_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


# --------- Колбэки для монитора ---------
async def push_deal(deal_id: int) -> None:
    """Отправляет владельцу карточку выгодной сделки (вызывается вотчером)."""
    async with get_session() as session:
        deal = await deals_service.get_deal(session, deal_id)
        if not deal:
            return
        card = "🚨 <b>Новый выгодный вариант!</b>\n\n" + formatting.deal_card(deal)
    await get_bot().send_message(
        settings.owner_telegram_id, card,
        reply_markup=keyboards.deal_actions(deal_id),
        disable_web_page_preview=True,
    )


async def send_alert(text: str) -> None:
    """Системное уведомление владельцу (капча, ошибки)."""
    try:
        await get_bot().send_message(settings.owner_telegram_id, text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось отправить alert: %s", exc)


async def push_reminder(deal_id: int, text: str) -> None:
    """Напоминание по сделке с кнопками действий."""
    try:
        await get_bot().send_message(
            settings.owner_telegram_id, f"🔔 {text}",
            reply_markup=keyboards.deal_actions(deal_id),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось отправить напоминание: %s", exc)


async def run_bot() -> None:
    bot = get_bot()
    dp = build_dispatcher()
    logger.info("Бот запускается (polling)…")
    await dp.start_polling(bot, handle_signals=False)
