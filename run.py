"""Точка входа: запускает бота, веб-сервер (Mini App) и watcher в одном процессе."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

import uvicorn

from app.config import settings
from app.db import init_db

# Windows-консоль по умолчанию не UTF-8 — без этого русские логи превращаются в кракозябры.
for stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        stream.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("solomoney")


async def _run_web() -> None:
    from app.web.api import app

    config = uvicorn.Config(
        app, host=settings.web_host, port=settings.web_port,
        log_level="warning", loop="asyncio",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def _ensure_playwright_browser() -> None:
    """Best-effort: гарантирует наличие Chromium для Playwright.

    На Replit (импорт из zip) системный браузер из replit.nix может быть недоступен,
    а без браузера мониторинг тихо падает. Если задан системный Chromium
    (PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) — ничего не делаем. Иначе один раз ставим
    браузер Playwright. Не блокирует старт бота/веба и не валит процесс при ошибке.
    """
    import os

    if os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
        return  # используется системный Chromium (Nix) — установка не нужна
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        logger.info("Проверяю/ставлю Chromium для Playwright (это разово)…")
        await proc.communicate()
        if proc.returncode == 0:
            logger.info("Chromium для Playwright готов")
        else:
            logger.warning(
                "playwright install завершился с кодом %s — мониторинг сообщит, "
                "если браузер не запустится", proc.returncode,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Не удалось установить браузер Playwright автоматически: %s", exc)


async def main() -> None:
    await init_db()
    logger.info("База данных готова: %s", settings.db_path)

    tasks: list[asyncio.Task] = []

    # Веб-сервер (Mini App + health для keep-alive на Replit) — всегда.
    tasks.append(asyncio.create_task(_run_web(), name="web"))
    logger.info("Веб-дашборд: http://localhost:%s", settings.web_port)

    # Монитор + бот + напоминания, если настроены.
    mon = None
    reminder_stop = asyncio.Event()
    if settings.bot_enabled:
        from app.bot.main import push_deal, push_reminder, run_bot, send_alert
        from app.core.reminders import run_reminder_loop
        from app.watcher.monitor import Monitor

        mon = Monitor(on_deal=push_deal, on_alert=send_alert)
        # Обеспечиваем браузер для мониторинга в фоне (не задерживает старт бота).
        if settings.watcher_enabled:
            tasks.append(asyncio.create_task(
                _ensure_playwright_browser(), name="playwright-setup"))
        tasks.append(asyncio.create_task(run_bot(), name="bot"))
        tasks.append(asyncio.create_task(mon.run(), name="watcher"))
        tasks.append(asyncio.create_task(
            run_reminder_loop(push_reminder, reminder_stop), name="reminders"))
        logger.info("Бот, мониторинг и напоминания запущены")
    else:
        logger.warning(
            "BOT_TOKEN/OWNER_TELEGRAM_ID не заданы — работает только веб-дашборд. "
            "Заполни .env, чтобы включить Telegram-бота и мониторинг."
        )

    stop = asyncio.Event()

    def _handle_stop() -> None:
        logger.info("Останавливаюсь…")
        if mon:
            mon.stop()
        reminder_stop.set()
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_stop)
        except NotImplementedError:  # Windows
            pass

    try:
        await stop.wait()
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
