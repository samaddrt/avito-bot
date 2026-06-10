"""Детерминированный слой оценки поверх Gemini.

Принцип: Gemini даёт совещательный вывод, но финальный вердикт, цифры и hotness
считаем формулами и жёсткими правилами — чтобы решения были проверяемыми и
система не «велась» на красивые слова модели.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import settings
from app.core import pricebook
from app.schemas import DealAnalysis


@dataclass
class ScoredDeal:
    """Итог скоринга — то, что сохраняем в Deal и показываем пользователю."""

    market_price: int
    quick_sale_price: int
    target_buy_price: int
    gross_profit: int          # до вычета расходов
    expected_costs: int        # дорога/комиссия/ремонт (прогноз)
    profit: int                # ЧИСТАЯ прибыль = gross - costs
    margin_pct: float          # маржа по чистой прибыли
    liquidity: str
    risk_score: int
    days_to_sell_est: int
    hotness: float
    verdict: str
    reasons: list[str] = field(default_factory=list)   # почему именно такой вердикт
    scam_flags: list[str] = field(default_factory=list)


# Слова-маркеры риска в тексте объявления
_SCAM_TOKENS = [
    ("предоплат", "просит предоплату"),
    ("только доставк", "только доставка, без личной встречи"),
    ("залог", "просит залог"),
    ("аванс", "просит аванс"),
    ("перевод на карт", "просит перевод на карту до встречи"),
    ("отправлю после оплаты", "отправка только после оплаты"),
    ("срочно уезжаю", "давит срочностью ('срочно уезжаю')"),
    ("курьер", "настаивает на курьере/доставке"),
    ("сбербанк онлайн", "просит перевод"),
]

_LIQUIDITY_DAYS = {"high": 3, "medium": 7, "low": 14}
_LIQUIDITY_WEIGHT = {"high": 1.0, "medium": 0.7, "low": 0.4}

# Ориентир расходов по категориям сверх базовых (комиссия Avito-доставки, чистка и т.п.).
_CATEGORY_COST = {"ps5": 500, "macbook_air": 1500, "iphone": 800, "other": 800}


def estimate_costs(category: str | None) -> int:
    from app.config import settings as _s

    return _s.default_cost_rub + _CATEGORY_COST.get(category or "other", 800)


def detect_text_scam_flags(raw_text: str) -> list[str]:
    text = (raw_text or "").lower()
    flags = []
    for token, label in _SCAM_TOKENS:
        if token in text:
            flags.append(label)
    return flags


def score(analysis: DealAnalysis, raw_text: str = "", category: str | None = None,
          model_name: str | None = None, seller_price: int | None = None) -> ScoredDeal:
    """Главная функция: берёт вывод Gemini, сверяет с прайсбуком и правилами."""
    reasons: list[str] = []

    market = max(analysis.market_price, 0)
    quick = max(analysis.quick_sale_price, 0)

    # 1) Сверка с прайсбуком — он приоритетнее, если расхождение велико.
    pb = pricebook.lookup(category, model_name)
    if pb:
        pb_market = pb["market_price"]
        pb_quick = pb["quick_sale_price"]
        if market == 0 or abs(market - pb_market) / pb_market > 0.25:
            reasons.append(
                f"Цена Gemini ({market}₽) расходится с прайсбуком ({pb_market}₽) — берём прайсбук"
            )
            market = pb_market
        if quick == 0 or abs(quick - pb_quick) / pb_quick > 0.25:
            quick = pb_quick
    else:
        reasons.append("Нет записи в прайсбуке — опираемся на оценку Gemini")

    # 2) Целевая цена покупки и прибыль (страхуемся, что цель не выше быстрой продажи).
    target = analysis.expected_buy_price or 0
    if target <= 0 or target >= quick:
        # запасная эвристика: целимся в 88% быстрой цены
        target = int(quick * 0.88)
        reasons.append("Целевая цена покупки пересчитана по формуле (88% быстрой цены)")

    gross_profit = quick - target
    costs = estimate_costs(category)
    profit = gross_profit - costs  # чистая прибыль
    margin = (profit / target * 100) if target > 0 else 0.0

    liquidity = analysis.liquidity.value if hasattr(analysis.liquidity, "value") else str(analysis.liquidity)
    days = analysis.days_to_sell_est or _LIQUIDITY_DAYS.get(liquidity, 7)

    # 3) Скам-флаги: объединяем Gemini + текстовые маркеры.
    scam_flags = list(dict.fromkeys((analysis.scam_flags or []) + detect_text_scam_flags(raw_text)))
    risk = int(analysis.risk_score or 0)

    # Аномально низкая цена дорогого товара -> жёсткий риск.
    # Берём явно распознанную цену продавца, иначе пытаемся вытащить из текста.
    sp = seller_price or _extract_seller_price(raw_text)
    if sp and market and sp < market * 0.55 and market >= 25000:
        risk = max(risk, 85)
        scam_flags.append(f"Цена {sp}₽ — менее 55% рынка ({market}₽): типичная приманка")

    if scam_flags:
        risk = max(risk, 60)

    risk = max(0, min(100, risk))

    # 4) Финальный вердикт по правилам (Gemini — только совещательно).
    verdict = _decide_verdict(profit, margin, risk, reasons)

    # 5) Hotness: маржа × ликвидность × (низкий риск). Чем выше — тем приоритетнее пуш.
    liq_w = _LIQUIDITY_WEIGHT.get(liquidity, 0.6)
    risk_factor = max(0.0, 1 - risk / 100)
    hotness = round(margin * liq_w * risk_factor, 1)

    return ScoredDeal(
        market_price=market,
        quick_sale_price=quick,
        target_buy_price=target,
        gross_profit=gross_profit,
        expected_costs=costs,
        profit=profit,
        margin_pct=round(margin, 1),
        liquidity=liquidity,
        risk_score=risk,
        days_to_sell_est=days,
        hotness=hotness,
        verdict=verdict,
        reasons=reasons,
        scam_flags=scam_flags,
    )


def _decide_verdict(profit: int, margin: float, risk: int, reasons: list[str]) -> str:
    if risk >= 70:
        reasons.append(f"Риск {risk}/100 ≥ 70 → HIGH_RISK")
        return "HIGH_RISK"
    if profit < settings.min_profit_rub or margin < settings.min_margin_pct:
        reasons.append(
            f"Прибыль {profit}₽ или маржа {margin:.0f}% ниже порога "
            f"({settings.min_profit_rub}₽ / {settings.min_margin_pct:.0f}%) → SKIP"
        )
        return "SKIP"
    # Хорошая экономика, риск умеренный.
    if risk >= 45:
        reasons.append(f"Экономика ок, но риск {risk}/100 → WATCH (нужна проверка)")
        return "WATCH"
    if margin >= 25 and profit >= settings.min_profit_rub * 2 and risk < 30:
        reasons.append(f"Жирная маржа {margin:.0f}% и низкий риск → BUY_NOW")
        return "BUY_NOW"
    reasons.append(f"Хорошая сделка с торгом: маржа {margin:.0f}%, риск {risk} → NEGOTIATE")
    return "NEGOTIATE"


def _extract_seller_price(raw_text: str) -> int | None:
    """Грубая эвристика для извлечения цены из текста — для правила аномалии."""
    import re

    if not raw_text:
        return None
    # ищем числа рядом со знаком ₽ или 'руб'
    candidates = re.findall(r"(\d[\d\s]{3,})\s*(?:₽|руб|р\.)", raw_text.lower())
    prices = []
    for c in candidates:
        digits = re.sub(r"\s", "", c)
        if digits.isdigit():
            prices.append(int(digits))
    return min(prices) if prices else None
