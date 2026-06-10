"""Каталог товаров и опорных цен: загрузка, нечёткий поиск, CRUD.

Категории и модели задаёт пользователь (не захардкожены). У каждой модели —
рыночная цена, цена быстрой продажи и ликвидность (high/medium/low).
"""
from __future__ import annotations

import datetime
import json
import re
from functools import lru_cache

from app.config import settings

_VALID_LIQUIDITY = {"high", "medium", "low"}


@lru_cache(maxsize=1)
def _load_raw() -> dict:
    path = settings.pricebook_path
    if not path.exists():
        return {"items": {}}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_raw(data: dict) -> None:
    data["updated"] = datetime.date.today().isoformat()
    with open(settings.pricebook_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    reload()


def reload() -> None:
    _load_raw.cache_clear()


def categories() -> list[str]:
    """Список категорий каталога (служебные ключи с '_' игнорируются)."""
    return [c for c in _load_raw().get("items", {}) if not c.startswith("_")]


def find_category_of(model_name: str) -> str | None:
    for cat, models in _load_raw().get("items", {}).items():
        if model_name in models:
            return cat
    return None


def upsert_prices(category: str, model_name: str, market_price: int,
                  quick_sale_price: int, liquidity: str | None = None) -> None:
    """Создаёт/обновляет запись модели и сохраняет каталог."""
    data = _load_raw() if settings.pricebook_path.exists() else {"items": {}}
    items = data.setdefault("items", {}).setdefault(category, {})
    existing = items.get(model_name, {})
    liq = (liquidity or existing.get("liquidity") or "medium").lower()
    if liq not in _VALID_LIQUIDITY:
        liq = "medium"
    items[model_name] = {
        "market_price": int(market_price),
        "quick_sale_price": int(quick_sale_price),
        "liquidity": liq,
    }
    _save_raw(data)


# Понятные псевдонимы для UI
add_product = upsert_prices


def remove_product(model_name: str) -> bool:
    data = _load_raw()
    for cat, models in data.get("items", {}).items():
        if model_name in models:
            del models[model_name]
            if not models:
                del data["items"][cat]
            _save_raw(data)
            return True
    return False


def list_products() -> list[dict]:
    """Полный каталог как список словарей (для бота/дашборда/подбора)."""
    out: list[dict] = []
    for cat, models in _load_raw().get("items", {}).items():
        if cat.startswith("_"):
            continue
        for name, p in models.items():
            out.append({
                "category": cat,
                "model_name": name,
                "market_price": p["market_price"],
                "quick_sale_price": p["quick_sale_price"],
                "liquidity": p.get("liquidity", "medium"),
            })
    return out


def all_models() -> list[str]:
    return [p["model_name"] for p in list_products()]


def pricebook_summary() -> str:
    """Краткий текст для подсказки Gemini — опорные цены."""
    lines = [
        f"- {p['model_name']}: рынок {p['market_price']}₽, быстрая {p['quick_sale_price']}₽"
        for p in list_products()
    ]
    return "\n".join(lines)


def _normalize(text: str) -> set[str]:
    text = re.sub(r"[^a-z0-9а-я]+", " ", text.lower())
    return {t for t in text.split() if t}


def lookup(category: str | None, model_name: str | None) -> dict | None:
    """Нечётко находит запись по категории и названию модели."""
    data = _load_raw().get("items", {})
    if not model_name:
        return None

    query_tokens = _normalize(model_name)
    candidates: list[tuple[int, str, dict]] = []

    search_space: dict = {}
    if category and category in data:
        search_space = data[category]
    else:
        for cat, models in data.items():
            if not cat.startswith("_"):
                search_space.update(models)

    for name, prices in search_space.items():
        overlap = len(query_tokens & _normalize(name))
        if overlap:
            candidates.append((overlap, name, prices))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    _, name, prices = candidates[0]
    return {
        "name": name,
        "market_price": prices["market_price"],
        "quick_sale_price": prices["quick_sale_price"],
        "liquidity": prices.get("liquidity", "medium"),
    }
