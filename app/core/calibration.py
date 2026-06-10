"""Самокалибровка прайсбука по фактическим продажам.

Берёт закрытые сделки (sold) с фактическими ценами, группирует по модели и
предлагает обновить опорные цены: market_price ≈ медиана фактических продаж,
quick_sale_price ≈ ~92% от неё. Применять предложения — по явной команде.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import pricebook
from app.models import Deal, DealStatus

_MIN_SAMPLES = 2  # сколько продаж нужно, чтобы доверять статистике


@dataclass
class PriceSuggestion:
    category: str
    model_name: str
    samples: int
    current_market: int | None
    suggested_market: int
    suggested_quick: int

    @property
    def changed(self) -> bool:
        if self.current_market is None:
            return True
        return abs(self.suggested_market - self.current_market) / self.current_market > 0.05


async def suggest(session: AsyncSession) -> list[PriceSuggestion]:
    res = await session.execute(
        select(Deal).where(
            Deal.status == DealStatus.sold,
            Deal.actual_sell_price.isnot(None),
            Deal.model_name.isnot(None),
        )
    )
    deals = list(res.scalars().all())

    grouped: dict[tuple[str, str], list[int]] = {}
    for d in deals:
        key = (d.category or "other", d.model_name)
        grouped.setdefault(key, []).append(d.actual_sell_price)

    suggestions: list[PriceSuggestion] = []
    for (category, model), prices in grouped.items():
        if len(prices) < _MIN_SAMPLES:
            continue
        med = int(statistics.median(prices))
        current = pricebook.lookup(category, model)
        suggestions.append(
            PriceSuggestion(
                category=category,
                model_name=model,
                samples=len(prices),
                current_market=current["market_price"] if current else None,
                suggested_market=med,
                suggested_quick=int(med * 0.92),
            )
        )
    return [s for s in suggestions if s.changed]


def apply(suggestions: list[PriceSuggestion]) -> int:
    """Записывает предложения в pricebook.json. Возвращает число обновлённых моделей."""
    n = 0
    for s in suggestions:
        cat = pricebook.find_category_of(s.model_name) or s.category
        pricebook.upsert_prices(cat, s.model_name, s.suggested_market, s.suggested_quick)
        n += 1
    return n
