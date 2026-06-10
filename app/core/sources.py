"""Абстракция источника объявлений.

ListingSource — интерфейс. Сейчас есть PlaywrightSource (аккуратный сбор со
страницы поиска через реальный браузер, без обхода защит) и ManualSource (ручной
ввод). На будущее сюда же добавляется адаптер легального парсер-API одной заменой.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RawListing:
    """Сырое объявление из источника до анализа."""

    avito_id: str
    title: str
    url: str
    price: int | None = None
    description: str = ""
    city: str = ""
    category_hint: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def combined_text(self) -> str:
        parts = [self.title]
        if self.price:
            parts.append(f"Цена: {self.price} ₽")
        if self.city:
            parts.append(f"Город: {self.city}")
        if self.description:
            parts.append(self.description)
        return "\n".join(p for p in parts if p)


class CaptchaError(RuntimeError):
    """Источник наткнулся на капчу/блокировку. Обходить нельзя — сигналим наверх."""


class ListingSource(Protocol):
    async def fetch_new(self) -> list[RawListing]:  # pragma: no cover - интерфейс
        ...
