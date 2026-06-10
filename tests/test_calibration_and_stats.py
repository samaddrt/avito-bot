"""Интеграционные тесты на in-memory SQLite: калибровка, подбор по бюджету, статистика."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import calibration, opportunities, pricebook
from app.core import deals as deals_service
from app.models import Base, Deal, DealStatus


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def _sold_deal(model: str, buy: int, sell: int, category: str = "ps5") -> Deal:
    d = Deal()
    d.title = model
    d.model_name = model
    d.category = category
    d.status = DealStatus.sold
    d.actual_buy_price = buy
    d.actual_sell_price = sell
    d.extra_costs = 0
    return d


async def test_calibration_needs_two_samples(session, data_dir):
    session.add(_sold_deal("PS5 Slim", 28000, 36000))
    await session.flush()
    assert await calibration.suggest(session) == []


async def test_calibration_suggests_median(session, data_dir):
    pricebook.upsert_prices("ps5", "PS5 Slim", 41000, 37000)
    for sell in (34000, 36000, 38000):
        session.add(_sold_deal("PS5 Slim", 28000, sell))
    await session.flush()

    suggestions = await calibration.suggest(session)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert s.suggested_market == 36000  # медиана
    assert s.suggested_quick == int(36000 * 0.92)
    assert s.samples == 3

    # apply переписывает прайсбук.
    assert calibration.apply(suggestions) == 1
    assert pricebook.lookup("ps5", "PS5 Slim")["market_price"] == 36000


async def test_opportunities_respect_budget(session, data_dir):
    pricebook.upsert_prices("ps5", "PS5 Slim", 40000, 36000, "high")
    pricebook.upsert_prices("macbook_air", "MacBook Air M2", 70000, 64000, "medium")

    opps = await opportunities.suggest_for_budget(session, budget=40000)
    names = [o.model_name for o in opps]
    assert "PS5 Slim" in names          # est_buy ~31200 — влезает
    assert "MacBook Air M2" not in names  # est_buy ~54600 — не влезает
    assert all(o.net_profit > 0 for o in opps)


async def test_opportunities_zero_budget(session, data_dir):
    assert await opportunities.suggest_for_budget(session, budget=0) == []


async def test_stats_realized_profit_and_funnel(session, data_dir):
    d = _sold_deal("PS5 Slim", 28000, 36000)
    d.extra_costs = 1000
    session.add(d)
    session.add(_sold_deal("iPhone 14", 40000, 38000, category="iphone"))  # минусовая
    await session.flush()

    s = await deals_service.stats(session)
    assert s["sold_count"] == 2
    assert s["realized_profit"] == (36000 - 28000 - 1000) + (38000 - 40000)
    assert s["win_rate"] == 50
    assert s["funnel"]["sold"] == 2
