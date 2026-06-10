"""Общие фикстуры: изолируем data/ во временную папку, чтобы тесты
не трогали реальные pricebook.json / searches.json / БД."""
from __future__ import annotations

import pytest

from app import config
from app.core import pricebook


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Подменяет каталог данных на временный и сбрасывает кэш прайсбука."""
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    pricebook.reload()
    yield tmp_path
    pricebook.reload()
