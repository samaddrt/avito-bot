"""Аккуратный сбор объявлений со страницы поиска Avito через Playwright.

ВАЖНО: никакого обхода защит. Браузер ведёт себя как обычный пользователь,
заходит редко. Если Avito показывает капчу/блокировку — мы НЕ пытаемся её решать,
а поднимаем CaptchaError, чтобы монитор поставил паузу и уведомил владельца.

Браузер один на весь проход мониторинга: монитор открывает AvitoBrowser как
async-контекст и ходит по всем поискам/карточкам в одной сессии. Это быстрее
(не запускаем Chromium на каждую страницу) и ближе к поведению живого человека.
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


def _abs_url(href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http"):
        return href
    return f"https://www.avito.ru{href}"


class AvitoBrowser:
    """Одна браузерная сессия на весь проход мониторинга.

    Использование:
        async with AvitoBrowser() as br:
            items = await br.fetch_search(search)
            desc = await br.fetch_detail(items[0].url)
    """

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "AvitoBrowser":
        try:
            from playwright.async_api import async_playwright  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Playwright не установлен. Выполни: pip install playwright && playwright install chromium"
            ) from exc

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=settings.watch_headless)
        self._context = await self._browser.new_context(
            user_agent=_USER_AGENT,
            locale="ru-RU",
            viewport={"width": 1366, "height": 900},
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    await closer.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self._context = None

    async def _open_page(self, url: str, settle_ms: int, captcha_hint: str):
        """Открывает URL в новой вкладке и проверяет на блокировку. Вкладку закрывает вызывающий."""
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(settle_ms)
            body_text = (await page.inner_text("body")).lower()
            if any(m in body_text for m in _BLOCK_MARKERS):
                raise CaptchaError(captcha_hint)
            return page
        except BaseException:
            await page.close()
            raise

    async def fetch_search(self, search: SavedSearch) -> list[RawListing]:
        """Открывает страницу поиска и извлекает карточки первой страницы.

        Дедупликация по avito_id выполняется выше (в мониторе).
        """
        page = await self._open_page(
            search.url, settle_ms=2500,
            captcha_hint=f"Avito показал проверку на поиске '{search.name}'",
        )
        try:
            results: list[RawListing] = []
            items = await page.query_selector_all('[data-marker="item"]')
            for item in items:
                parsed = await _extract_card(item, search)
                if parsed:
                    results.append(parsed)
            return results
        finally:
            await page.close()

    async def fetch_detail(self, url: str) -> str:
        """Догружает полное описание объявления (для лучшего анализа). Best-effort."""
        page = await self._open_page(
            url, settle_ms=2000,
            captcha_hint="Avito показал проверку на карточке объявления",
        )
        try:
            desc_el = await page.query_selector('[data-marker="item-view/item-description"]')
            return (await desc_el.inner_text()).strip() if desc_el else ""
        finally:
            await page.close()


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
