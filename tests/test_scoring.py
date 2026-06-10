"""Тесты детерминированного скоринга — главного «предохранителя» системы."""
from __future__ import annotations

from app.core import pricebook, scoring
from app.schemas import DealAnalysis, LiquidityEnum, VerdictEnum


def make_analysis(**overrides) -> DealAnalysis:
    base = dict(
        market_price=40000,
        quick_sale_price=36000,
        expected_buy_price=28000,
        profit=8000,
        margin_pct=28.0,
        liquidity=LiquidityEnum.high,
        days_to_sell_est=3,
        risk_score=10,
        scam_flags=[],
        why_good="Цена ниже рынка",
        what_to_check=[],
        questions_to_seller=[],
        meeting_checklist=[],
        verdict=VerdictEnum.BUY_NOW,
    )
    base.update(overrides)
    return DealAnalysis(**base)


def test_good_deal_buy_now(data_dir, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "min_profit_rub", 3000)
    monkeypatch.setattr(settings, "min_margin_pct", 12.0)
    # Покупка за 26000 при быстрой продаже 36000: маржа >25% даже после расходов.
    s = scoring.score(make_analysis(expected_buy_price=26000),
                      category="ps5", model_name="PS5 Slim")
    assert s.verdict == "BUY_NOW"
    assert s.profit == 36000 - 26000 - s.expected_costs
    assert s.gross_profit == 10000
    assert s.hotness > 0


def test_high_risk_overrides_economics(data_dir):
    s = scoring.score(make_analysis(risk_score=80))
    assert s.verdict == "HIGH_RISK"


def test_low_profit_skipped(data_dir):
    s = scoring.score(make_analysis(
        quick_sale_price=29000, expected_buy_price=28000, profit=1000, margin_pct=3.5,
    ))
    assert s.verdict == "SKIP"


def test_moderate_risk_watch(data_dir):
    s = scoring.score(make_analysis(risk_score=50))
    assert s.verdict == "WATCH"


def test_scam_flags_raise_risk_floor(data_dir):
    s = scoring.score(make_analysis(scam_flags=["просит предоплату"]))
    assert s.risk_score >= 60


def test_text_scam_markers_detected():
    flags = scoring.detect_text_scam_flags(
        "Продам PS5, нужна предоплата, отправлю после оплаты"
    )
    assert "просит предоплату" in flags
    assert "отправка только после оплаты" in flags
    assert scoring.detect_text_scam_flags("Обычное объявление, самовывоз") == []


def test_anomalously_low_price_flagged(data_dir):
    # 15000₽ при рынке 40000₽ — типичная приманка.
    s = scoring.score(make_analysis(), raw_text="PS5 за 15000 ₽ срочно", seller_price=15000)
    assert s.risk_score >= 85
    assert any("приманка" in f for f in s.scam_flags)


def test_pricebook_overrides_gemini_prices(data_dir):
    pricebook.upsert_prices("ps5", "PS5 Slim", 41000, 37000, "high")
    # Gemini «увидел» рынок в 2 раза выше прайсбука — верим прайсбуку.
    s = scoring.score(make_analysis(market_price=80000), category="ps5", model_name="PS5 Slim")
    assert s.market_price == 41000


def test_target_recomputed_when_above_quick_sale(data_dir):
    s = scoring.score(make_analysis(expected_buy_price=37000))  # выше quick_sale 36000
    assert s.target_buy_price == int(36000 * 0.88)


def test_extract_seller_price():
    assert scoring._extract_seller_price("Цена 28 000 ₽, торг") == 28000
    assert scoring._extract_seller_price("без цены") is None
