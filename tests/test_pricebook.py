"""Тесты каталога/прайсбука: CRUD и нечёткий поиск."""
from __future__ import annotations

from app.core import pricebook


def test_upsert_and_lookup(data_dir):
    pricebook.upsert_prices("iphone", "iPhone 14 128GB", 45000, 41000, "high")
    hit = pricebook.lookup("iphone", "iPhone 14")
    assert hit is not None
    assert hit["market_price"] == 45000
    assert hit["liquidity"] == "high"


def test_lookup_prefers_exact_over_longer_name(data_dir):
    pricebook.upsert_prices("iphone", "iPhone 14", 45000, 41000)
    pricebook.upsert_prices("iphone", "iPhone 14 Pro Max", 75000, 70000)
    hit = pricebook.lookup("iphone", "iPhone 14")
    assert hit["name"] == "iPhone 14"


def test_lookup_across_categories_when_unknown(data_dir):
    pricebook.upsert_prices("ps5", "PS5 Slim Digital", 40000, 36000)
    hit = pricebook.lookup(None, "ps5 slim")
    assert hit is not None
    assert hit["name"] == "PS5 Slim Digital"


def test_lookup_miss_returns_none(data_dir):
    pricebook.upsert_prices("ps5", "PS5 Slim", 40000, 36000)
    assert pricebook.lookup("ps5", "Xbox Series X") is None
    assert pricebook.lookup("ps5", None) is None


def test_remove_product_and_empty_category(data_dir):
    pricebook.upsert_prices("airpods", "AirPods Pro 2", 18000, 16000)
    assert pricebook.remove_product("AirPods Pro 2") is True
    assert pricebook.remove_product("AirPods Pro 2") is False
    assert "airpods" not in pricebook.categories()


def test_invalid_liquidity_falls_back_to_medium(data_dir):
    pricebook.upsert_prices("ps5", "PS5", 40000, 36000, "ultra")
    assert pricebook.lookup("ps5", "PS5")["liquidity"] == "medium"


def test_list_products_skips_service_keys(data_dir):
    pricebook.upsert_prices("ps5", "PS5", 40000, 36000)
    products = pricebook.list_products()
    assert len(products) == 1
    assert products[0]["model_name"] == "PS5"
