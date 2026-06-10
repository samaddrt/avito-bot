"""Точка входа: запускает бота, веб-сервер (Mini App) и watcher в одном процессе."""
from __future__ import annotations

import asyncio
import logging
import signal

import uvicorn

from app.config import settings
from app.db import init_db

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
