"""Аккуратный сбор объявлений со страницы поиска Avito через Playwright.

ВАЖНО: никакого обхода защит. Браузер ведёт себя как обычный пользователь,
заходит редко. Если Avito показывает капчу/блокировку — мы НЕ пытаемся её решать,
а поднимаем CaptchaError, чтобы монитор поставил паузу и уведомил владельца.
"""
from __future__ import annotations

import logging
import re

from app.config import settings
from app.core.sources import CaptchaError, RawListing
from app.watcher.searches import SavedSearch

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Маркеры страницы блокировки/капчи Avito.
_BLOCK_MARKERS = [
    "доступ ограничен",
    "подтвердите, что вы не робот",
    "firewall",
    "проверка безопасности",
    "captcha",
    "i'm not a robot",
]


def _parse_price(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


async def fetch_search(search: SavedSearch, max_detail: int = 4) -> list[RawListing]:
    """Открывает страницу поиска, извлекает карточки, догружает описания для новых.

    Дедупликация по avito_id выполняется выше (в мониторе) — здесь возвращаем всё,
    что видим на первой странице.
    """
    try:
        from playwright.async_api import async_playwright  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Playwright не установлен. Выполни: pip install playwright && playwright install chromium"
        ) from exc

    results: list[RawListing] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=settings.watch_headless)
        context = await browser.new_context(
            user_agent=_USER_AGENT,
            locale="ru-RU",
            viewport={"width": 1366, "height": 900},
        )
        page = await context.new_page()
        try:
            await page.goto(search.url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)

            body_text = (await page.inner_text("body")).lower()
            if any(m in body_text for m in _BLOCK_MARKERS):
                raise CaptchaError(f"Avito показал проверку на поиске '{search.name}'")

            items = await page.query_selector_all('[data-marker="item"]')
            for item in items:
                parsed = await _extract_card(item, search)
                if parsed:
                    results.append(parsed)
        finally:
            await context.close()
            await browser.close()

    return results


async def _extract_card(item, search: SavedSearch) -> RawListing | None:
    try:
        avito_id = await item.get_attribute("data-item-id")
        title_el = await item.query_selector('[itemprop="name"], [data-marker="item-title"]')
        link_el = await item.query_selector('a[data-marker="item-title"], a[itemprop="url"], a')
        price_el = await item.query_selector('[itemprop="price"], [data-marker="item-price"], meta[itemprop="price"]')

        title = (await title_el.inner_text()).strip() if title_el else ""
        href = await link_el.get_attribute("href") if link_el else None
        url = _abs_url(href)

        price = None
        if price_el:
            content = await price_el.get_attribute("content")
            price = _parse_price(content) if content else _parse_price(await price_el.inner_text())

        if not avito_id and url:
            m = re.search(r"_(\d+)(?:\?|$)", url)
            avito_id = m.group(1) if m else None

        if not avito_id or not title:
            return None

        # Локальный ценовой фильтр.
        if price is not None:
            if search.min_price and price < search.min_price:
                return None
            if search.max_price and price > search.max_price:
                return None

        return RawListing(
            avito_id=str(avito_id),
            title=title,
            url=url or "",
            price=price,
            category_hint=search.category_hint,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Не удалось разобрать карточку: %s", exc)
        return None


async def fetch_detail(url: str) -> str:
    """Догружает полное описание объявления (для лучшего анализа). Best-effort."""
    try:
        from playwright.async_api import async_playwright  # noqa: WPS433
    except ImportError:  # pragma: no cover
        return ""

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=settings.watch_headless)
        context = await browser.new_context(user_agent=_USER_AGENT, locale="ru-RU")
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2000)
            body_text = (await page.inner_text("body")).lower()
            if any(m in body_text for m in _BLOCK_MARKERS):
                raise CaptchaError("Avito показал проверку на карточке объявления")
            desc_el = await page.query_selector('[data-marker="item-view/item-description"]')
            return (await desc_el.inner_text()).strip() if desc_el else ""
        finally:
            await context.close()
            await browser.close()


def _abs_url(href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http"):
        return href
    return f"https://www.avito.ru{href}"
