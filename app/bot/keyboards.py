"""Inline-клавиатуры бота."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import settings


def deal_actions(deal_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💬 Сообщения для торга", callback_data=f"msg:{deal_id}")
    b.button(text="📌 В сделки", callback_data=f"status:{deal_id}:contacted")
    b.button(text="👁 Наблюдать", callback_data=f"status:{deal_id}:watching")
    b.button(text="❌ Пропустить", callback_data=f"status:{deal_id}:skipped")
    b.button(text="📦 Куплено → перепродажа", callback_data=f"resale:{deal_id}")
    b.adjust(1, 2, 2)
    return b.as_markup()


def negotiation_tones(deal_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🙂 Вежливо", callback_data=f"tone:{deal_id}:polite")
    b.button(text="😐 Жёстко", callback_data=f"tone:{deal_id}:firm")
    b.button(text="🚗 Приеду сегодня", callback_data=f"tone:{deal_id}:quick_meet")
    b.adjust(3)
    return b.as_markup()


def deal_status_flow(deal_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Купил", callback_data=f"status:{deal_id}:bought")
    b.button(text="🏷 Выставил", callback_data=f"status:{deal_id}:listed")
    b.button(text="💰 Продал", callback_data=f"status:{deal_id}:sold")
    b.adjust(3)
    return b.as_markup()


def open_app() -> InlineKeyboardMarkup | None:
    if not settings.webapp_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="📊 Открыть дашборд",
                web_app={"url": settings.webapp_url},
            )
        ]]
    )
