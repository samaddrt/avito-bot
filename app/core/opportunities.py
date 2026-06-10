"""Подбор выгодных направлений под бюджет.

По каталогу оцениваем для каждой модели реалистичный флип: покупка по типичной
«выгодной» цене (рынок минус скидка, которую дают спешащие/неопытные продавцы),
быстрая продажа, минус расходы. Ранжируем по марже × ликвидность и фильтруем по
бюджету. Если по модели есть закрытые сделки — подмешиваем твою реальную маржу.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import pricebook
from app.core.scoring import estimate_costs
from app.models import Deal, DealStatus

_LIQ_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.45}
_LIQ_DAYS = {"high": 3, "medium": 7, "low": 14}


@dataclass
class Opportunity:
    category: str
    model_name: str
    liquidity: str
    market_price: int
    est_buy_price: int      # типичная цена покупки выгодного лота
    quick_sale_price: int
    costs: int
    net_profit: int         # за один флип
    margin_pct: float
    units: int              # сколько штук уместится в бюджет
    total_potential: int    # net × units
    est_days: int
    score: float
    real_data: bool         # маржа уточнена по твоим продажам


async def _realized_margins(session: AsyncSession) -> dict[str, float]:
    """Средняя фактическая маржа (net/buy) по модели из закрытых сделок."""
    res = await session.execute(
        select(Deal).where(
            Deal.status == DealStatus.sold,
            Deal.actual_buy_price.isnot(None),
            Deal.actual_sell_price.isnot(None),
            Deal.model_name.isnot(None),
        )
    )
    by_model: dict[str, list[float]] = {}
    for d in res.scalars().all():
        inv = (d.actual_buy_price or 0) + (d.extra_costs or 0)
        if inv > 0 and d.actual_profit is not None:
            by_model.setdefault(d.model_name, []).append(d.actual_profit / inv)
    return {m: sum(v) / len(v) for m, v in by_model.items()}


async def suggest_for_budget(session: AsyncSession, budget: int,
                             limit: int = 8) -> list[Opportunity]:
    if budget <= 0:
        return []

    discount = max(0.0, min(0.6, settings.opportunity_discount_pct / 100))
    realized = await _realized_margins(session)
    out: list[Opportunity] = []

    for p in pricebook.list_products():
        market = p["market_price"]
        quick = p["quick_sale_price"]
        liq = p.get("liquidity", "medium")
        est_buy = int(round(market * (1 - discount)))
        if est_buy <= 0 or est_buy > budget:
            continue

        costs = estimate_costs(p["category"])
        net = quick - est_buy - costs
        if net <= 0:
            continue
        margin = net / est_buy * 100

        # Подмешиваем реальную маржу, если есть статистика по модели.
        real = p["model_name"] in realized
        if real:
            margin = round((margin + realized[p["model_name"]] * 100) / 2, 1)

        units = max(1, budget // est_buy)
        total = net * units
        liq_w = _LIQ_WEIGHT.get(liq, 0.7)
        # Балл: маржа × ликвидность × лёгкий бонус за суммарный потенциал.
        score = round(margin * liq_w * (1 + min(units, 5) * 0.05), 1)

        out.append(Opportunity(
            category=p["category"], model_name=p["model_name"], liquidity=liq,
            market_price=market, est_buy_price=est_buy, quick_sale_price=quick,
            costs=costs, net_profit=net, margin_pct=round(margin, 1), units=units,
            total_potential=total, est_days=_LIQ_DAYS.get(liq, 7),
            score=score, real_data=real,
        ))

    out.sort(key=lambda o: o.score, reverse=True)
    return out[:limit]
