"""Сервисный слой работы со сделками: сохранение анализа, смена статуса, статистика.

Здесь сосредоточена вся запись в БД, чтобы бот, вотчер и API не дублировали логику.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.analyzer import AnalyzedListing
from app.models import Analysis, Deal, DealStatus, EventLog, Listing, Verdict


async def log_event(session: AsyncSession, kind: str, message: str,
                    deal_id: int | None = None, data: dict | None = None) -> None:
    session.add(EventLog(kind=kind, message=message, deal_id=deal_id, data=data))


async def save_analyzed(
    session: AsyncSession,
    result: AnalyzedListing,
    *,
    source: str = "manual",
    url: str | None = None,
    avito_id: str | None = None,
    city: str | None = None,
) -> Deal:
    """Создаёт Listing + Deal + Analysis из результата анализа."""
    listing = Listing(
        avito_id=avito_id,
        source=source,
        url=url,
        title=result.title,
        raw_text=result.raw_text,
        seller_price=result.parse.seller_price or None,
        city=city or (result.parse.city or None),
    )
    session.add(listing)
    await session.flush()

    s = result.scored
    deal = Deal(
        listing_id=listing.id,
        status=DealStatus.new,
        verdict=Verdict(s.verdict),
        title=result.title,
        category=result.parse.category,
        model_name=result.parse.model_name,
        url=url,
        city=city or (result.parse.city or None),
        seller_price=result.parse.seller_price or None,
        market_price=s.market_price,
        quick_sale_price=s.quick_sale_price,
        target_buy_price=s.target_buy_price,
        expected_costs=s.expected_costs,
        gross_profit=s.gross_profit,
        expected_profit=s.profit,
        margin_pct=s.margin_pct,
        liquidity=s.liquidity,
        risk_score=s.risk_score,
        hotness=s.hotness,
        days_to_sell_est=s.days_to_sell_est,
        next_action=_default_next_action(s.verdict),
    )
    session.add(deal)
    await session.flush()

    negotiation = None
    if result.negotiation:
        negotiation = result.negotiation.model_dump()

    analysis = Analysis(
        deal_id=deal.id,
        why_good=result.analysis.why_good,
        what_to_check=result.analysis.what_to_check,
        questions_to_seller=result.analysis.questions_to_seller,
        scam_flags=s.scam_flags,
        negotiation_messages=negotiation,
        meeting_checklist=result.analysis.meeting_checklist,
        raw_gemini=result.analysis.model_dump(mode="json"),
    )
    session.add(analysis)

    await log_event(
        session, "analyze", f"Проанализировано: {result.title} → {s.verdict}",
        deal_id=deal.id,
        data={"verdict": s.verdict, "profit": s.profit, "margin": s.margin_pct,
              "risk": s.risk_score, "reasons": s.reasons},
    )
    return deal


def _default_next_action(verdict: str) -> str:
    return {
        "BUY_NOW": "Написать продавцу и договориться о встрече сегодня",
        "NEGOTIATE": "Отправить сообщение для торга",
        "WATCH": "Наблюдать, перепроверить характеристики",
        "SKIP": "Пропущено",
        "HIGH_RISK": "Высокий риск — не связываться без проверки",
    }.get(verdict, "—")


# --------- Смена статуса с проставлением временных меток ---------
_STATUS_TIMESTAMP = {
    DealStatus.bought: "bought_at",
    DealStatus.listed: "listed_at",
    DealStatus.sold: "sold_at",
}


async def change_status(session: AsyncSession, deal: Deal, status: DealStatus,
                        next_action: str | None = None) -> Deal:
    old = deal.status
    deal.status = status
    ts_field = _STATUS_TIMESTAMP.get(status)
    if ts_field and getattr(deal, ts_field) is None:
        setattr(deal, ts_field, datetime.now(timezone.utc))
    if next_action is not None:
        deal.next_action = next_action
    await log_event(session, "status_change",
                    f"{deal.title}: {old.value} → {status.value}", deal_id=deal.id)
    return deal


async def get_deal(session: AsyncSession, deal_id: int) -> Deal | None:
    res = await session.execute(
        select(Deal).where(Deal.id == deal_id).options(
            selectinload(Deal.analysis), selectinload(Deal.listing)
        )
    )
    return res.scalar_one_or_none()


async def list_deals(session: AsyncSession, statuses: list[DealStatus] | None = None,
                     limit: int = 100) -> list[Deal]:
    stmt = select(Deal).options(selectinload(Deal.analysis)).order_by(
        Deal.hotness.desc().nullslast(), Deal.created_at.desc()
    ).limit(limit)
    if statuses:
        stmt = stmt.where(Deal.status.in_(statuses))
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def stats(session: AsyncSession) -> dict:
    """Сводная статистика: воронка, чистый заработок, ROI, win-rate, капитал, сроки."""
    from datetime import datetime, timedelta, timezone

    # Воронка по статусам
    res = await session.execute(select(Deal.status, func.count()).group_by(Deal.status))
    funnel = {row[0].value: row[1] for row in res.all()}

    # Все проданные (агрегируем в Python, чтобы честно учесть расходы и ROI).
    res = await session.execute(
        select(Deal).where(
            Deal.status == DealStatus.sold,
            Deal.actual_buy_price.isnot(None),
            Deal.actual_sell_price.isnot(None),
        )
    )
    sold = list(res.scalars().all())

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def _aware(dt):
        return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt

    realized = sum(d.actual_profit or 0 for d in sold)
    invested = sum(d.invested or 0 for d in sold)
    wins = sum(1 for d in sold if (d.actual_profit or 0) > 0)
    week_profit = sum((d.actual_profit or 0) for d in sold if _aware(d.sold_at) and _aware(d.sold_at) >= week_ago)
    month_profit = sum((d.actual_profit or 0) for d in sold if _aware(d.sold_at) and _aware(d.sold_at) >= month_ago)

    # Средний срок продажи (между покупкой/выставлением и продажей).
    durations = []
    for d in sold:
        start = _aware(d.listed_at) or _aware(d.bought_at)
        end = _aware(d.sold_at)
        if start and end and end >= start:
            durations.append((end - start).days)
    avg_days = round(sum(durations) / len(durations), 1) if durations else None

    # Замороженный капитал: куплено, ещё не продано.
    res = await session.execute(
        select(Deal).where(Deal.status.in_([DealStatus.bought, DealStatus.listed]))
    )
    tied = [d.invested or (d.actual_buy_price or d.target_buy_price or 0) for d in res.scalars().all()]
    capital_tied = int(sum(tied))

    # Потенциальная чистая прибыль по активным
    active_statuses = [DealStatus.new, DealStatus.contacted, DealStatus.negotiating,
                       DealStatus.bought, DealStatus.listed, DealStatus.watching]
    res = await session.execute(
        select(func.sum(Deal.expected_profit)).where(Deal.status.in_(active_statuses))
    )
    potential = res.scalar() or 0

    return {
        "funnel": funnel,
        "sold_count": len(sold),
        "realized_profit": int(realized),
        "roi_pct": round(realized / invested * 100, 1) if invested else None,
        "win_rate": round(wins / len(sold) * 100) if sold else None,
        "avg_days_to_sell": avg_days,
        "week_profit": int(week_profit),
        "month_profit": int(month_profit),
        "capital_tied": capital_tied,
        "potential_profit": int(potential or 0),
    }


async def record_numbers(session: AsyncSession, deal: Deal, *, buy: int | None = None,
                         sell: int | None = None, costs: int | None = None,
                         offer: int | None = None, agreed: int | None = None,
                         seller_replied: bool | None = None) -> Deal:
    """Фиксирует фактические цифры сделки (покупка/продажа/расходы/торг)."""
    if buy is not None:
        deal.actual_buy_price = buy
    if sell is not None:
        deal.actual_sell_price = sell
    if costs is not None:
        deal.extra_costs = costs
    if offer is not None:
        deal.offer_price = offer
    if agreed is not None:
        deal.agreed_price = agreed
    if seller_replied is not None:
        deal.seller_replied = seller_replied
    await log_event(session, "record", f"Цифры обновлены по «{deal.title}»", deal_id=deal.id,
                    data={"buy": buy, "sell": sell, "costs": costs})
    return deal
