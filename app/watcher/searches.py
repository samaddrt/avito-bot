"""Сохранённые поиски Avito (data/searches.json): загрузка и управление."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from app.config import settings


@dataclass
class SavedSearch:
    name: str
    url: str
    enabled: bool = True
    category_hint: str | None = None
    min_price: int | None = None
    max_price: int | None = None


def _read_raw() -> dict:
    path = settings.searches_path
    if not path.exists():
        return {"searches": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_raw(data: dict) -> None:
    with open(settings.searches_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_searches() -> list[SavedSearch]:
    out: list[SavedSearch] = []
    for s in _read_raw().get("searches", []):
        if not s.get("url"):
            continue
        out.append(
            SavedSearch(
                name=s.get("name", "Без названия"),
                url=s["url"],
                enabled=s.get("enabled", True),
                category_hint=s.get("category_hint"),
                min_price=s.get("min_price"),
                max_price=s.get("max_price"),
            )
        )
    return out


def enabled_searches() -> list[SavedSearch]:
    return [s for s in load_searches() if s.enabled and s.url]


def save_searches(searches: list[SavedSearch]) -> None:
    data = _read_raw()
    data["searches"] = [asdict(s) for s in searches]
    _write_raw(data)


_CATEGORY_GUESS = [
    ("ps5", ["playstation", "ps5", "пристав"]),
    ("macbook_air", ["macbook", "макбук", "ноутбук"]),
    ("iphone", ["iphone", "айфон", "телефон"]),
]


def _guess_category(text: str) -> str | None:
    low = text.lower()
    for cat, tokens in _CATEGORY_GUESS:
        if any(t in low for t in tokens):
            return cat
    return None


def add_search(url: str, name: str | None = None, category_hint: str | None = None,
               min_price: int | None = None, max_price: int | None = None) -> SavedSearch:
    """Добавляет новый поиск (если такого URL ещё нет) и сохраняет."""
    if not re.match(r"^https?://", url):
        raise ValueError("URL должен начинаться с http(s)://")
    searches = load_searches()
    for s in searches:
        if s.url == url:
            return s  # уже есть
    new = SavedSearch(
        name=name or f"Поиск {len(searches) + 1}",
        url=url,
        enabled=True,
        category_hint=category_hint or _guess_category(name or "") or _guess_category(url),
        min_price=min_price,
        max_price=max_price,
    )
    searches.append(new)
    save_searches(searches)
    return new


def toggle_search(index: int) -> SavedSearch | None:
    """Включает/выключает поиск по индексу (0-based)."""
    searches = load_searches()
    if not 0 <= index < len(searches):
        return None
    searches[index].enabled = not searches[index].enabled
    save_searches(searches)
    return searches[index]


def remove_search(index: int) -> bool:
    searches = load_searches()
    if not 0 <= index < len(searches):
        return False
    searches.pop(index)
    save_searches(searches)
    return True
