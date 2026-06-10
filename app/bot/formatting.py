"""Форматирование карточек сделок для Telegram (HTML parse mode)."""
from __future__ import annotations

import html

from app.models import Deal

_VERDICT_BADGE = {
    "BUY_NOW": "🟢 БРАТЬ СРОЧНО",
    "NEGOTIATE": "🟡 ТОРГОВАТЬСЯ",
    "WATCH": "🔵 НАБЛЮДАТЬ",
    "SKIP": "⚪️ ПРОПУСТИТЬ",
    "HIGH_RISK": "🔴 ВЫСОКИЙ РИСК",
}

_LIQUIDITY_RU = {"high": "высокая", "medium": "средняя", "low": "низкая"}


def _money(v: int | None) -> str:
    if v is None:
        return "—"
    return f"{v:,}".replace(",", " ") + " ₽"


def verdict_badge(verdict: str | None) -> str:
    return _VERDICT_BADGE.get(verdict or "", "—")


def deal_card(deal: Deal) -> str:
    """Карточка сделки в формате из ТЗ."""
    a = deal.analysis
    why = (a.why_good if a and a.why_good else "—")
    checks = ""
    if a and a.what_to_check:
        checks = "\n".join(f"  • {html.escape(c)}" for c in a.what_to_check[:5])

    risk_line = f"{deal.risk_score}/100" if deal.risk_score is not None else "—"
    scam = ""
    if a and a.scam_flags:
        scam = "\n⚠️ <b>Флаги риска:</b>\n" + "\n".join(
            f"  • {html.escape(f)}" for f in a.scam_flags[:5]
        )

    liq = _LIQUIDITY_RU.get(deal.liquidity or "", deal.liquidity or "—")
    msg_block = ""
    nego = (a.negotiation_messages if a else None) or {}
    if nego.get("polite"):
        msg_block = f"\n💬 <b>Что написать продавцу:</b>\n<i>{html.escape(nego['polite'])}</i>"

    lines = [
        f"<b>{verdict_badge(deal.verdict)}</b>",
        f"🔥 Hotness: <b>{deal.hotness if deal.hotness is not None else '—'}</b>",
        "",
        f"<b>Товар:</b> {html.escape(deal.title)}",
        f"<b>Цена продавца:</b> {_money(deal.seller_price)}",
        f"<b>Рыночная цена:</b> {_money(deal.market_price)}",
        f"<b>Быстрая перепродажа:</b> {_money(deal.quick_sale_price)}",
        f"<b>Цель покупки:</b> {_money(deal.target_buy_price)}",
        f"<b>Расходы (дорога/комиссия):</b> ~{_money(deal.expected_costs)}",
        f"<b>Чистая прибыль:</b> {_money(deal.expected_profit)} (валовая {_money(deal.gross_profit)})",
        f"<b>Маржа:</b> {deal.margin_pct:.0f}%" if deal.margin_pct is not None else "<b>Маржа:</b> —",
        f"<b>Ликвидность:</b> {liq} (~{deal.days_to_sell_est or '?'} дн.)",
        f"<b>Риск:</b> {risk_line}",
        "",
        f"<b>Почему:</b> {html.escape(why)}",
    ]
    if checks:
        lines.append(f"<b>Что проверить:</b>\n{checks}")
    if scam:
        lines.append(scam)
    if msg_block:
        lines.append(msg_block)
    if deal.url:
        lines.append(f"\n🔗 <a href=\"{html.escape(deal.url)}\">Открыть на Avito</a>")
    lines.append(f"\n<b>Решение: {verdict_badge(deal.verdict)}</b>")
    return "\n".join(lines)


def short_line(deal: Deal) -> str:
    return (
        f"{verdict_badge(deal.verdict)} | {html.escape(deal.title)} | "
        f"профит {_money(deal.expected_profit)} | риск {deal.risk_score or '—'}"
    )


def resale_card(draft: dict) -> str:
    points = "\n".join(f"  • {html.escape(p)}" for p in draft.get("selling_points", [])[:6])
    faq = "\n".join(f"  • {html.escape(q)}" for q in draft.get("faq", [])[:6])
    return "\n".join([
        "📦 <b>Черновик объявления для перепродажи</b>",
        "",
        f"<b>Заголовок:</b> {html.escape(draft.get('title', ''))}",
        f"<b>Цена:</b> {_money(draft.get('price'))}",
        f"<b>Минимальная цена:</b> {_money(draft.get('min_price'))}",
        "",
        f"<b>Описание:</b>\n{html.escape(draft.get('description', ''))}",
        f"\n<b>Аргументы для покупателя:</b>\n{points}" if points else "",
        f"\n<b>Частые вопросы:</b>\n{faq}" if faq else "",
        f"\n<b>Стратегия снижения цены:</b>\n{html.escape(draft.get('price_drop_strategy', ''))}",
    ])
