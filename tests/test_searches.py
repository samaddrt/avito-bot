"""Тесты сохранённых поисков."""
from __future__ import annotations

import pytest

from app.watcher import searches


def test_add_search_and_dedup(data_dir):
    s = searches.add_search("https://www.avito.ru/moskva?q=ps5", name="PS5 Москва")
    assert s.name == "PS5 Москва"
    assert s.category_hint == "ps5"
    # Повторное добавление того же URL не создаёт дубликат.
    searches.add_search("https://www.avito.ru/moskva?q=ps5")
    assert len(searches.load_searches()) == 1


def test_add_search_rejects_bad_url(data_dir):
    with pytest.raises(ValueError):
        searches.add_search("not-a-url")


def test_toggle_and_enabled_filter(data_dir):
    searches.add_search("https://www.avito.ru/q1", name="один")
    searches.add_search("https://www.avito.ru/q2", name="два")
    assert len(searches.enabled_searches()) == 2
    toggled = searches.toggle_search(0)
    assert toggled.enabled is False
    assert len(searches.enabled_searches()) == 1
    assert searches.toggle_search(99) is None


def test_remove_search(data_dir):
    searches.add_search("https://www.avito.ru/q1")
    assert searches.remove_search(0) is True
    assert searches.remove_search(0) is False
    assert searches.load_searches() == []


def test_category_guess_from_url(data_dir):
    s = searches.add_search("https://www.avito.ru/moskva?q=macbook+air+m2")
    assert s.category_hint == "macbook_air"
