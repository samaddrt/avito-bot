"""Асинхронный слой БД (SQLAlchemy 2 + aiosqlite)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Base, WatcherState

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.db_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Сопоставление типов SQLAlchemy → SQLite для ALTER TABLE при миграции.
def _sqlite_type(col) -> str:
    name = col.type.__class__.__name__.upper()
    if "INT" in name or "BOOL" in name:
        return "INTEGER"
    if "FLOAT" in name or "NUMERIC" in name or "REAL" in name:
        return "REAL"
    if "JSON" in name:
        return "JSON"
    return "TEXT"


def _default_clause(col) -> str:
    if col.default is not None and getattr(col.default, "is_scalar", False):
        val = col.default.arg
        if isinstance(val, bool):
            return f" DEFAULT {1 if val else 0}"
        if isinstance(val, (int, float)):
            return f" DEFAULT {val}"
    return ""


def _migrate(sync_conn) -> None:
    """Добавляет недостающие столбцы в существующие таблицы (лёгкая миграция)."""
    Base.metadata.create_all(sync_conn)
    inspector_rows = {}
    for table in Base.metadata.sorted_tables:
        res = sync_conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")').fetchall()
        existing = {row[1] for row in res}
        inspector_rows[table.name] = existing
        for col in table.columns:
            if col.name not in existing:
                ddl = (
                    f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" '
                    f"{_sqlite_type(col)}{_default_clause(col)}"
                )
                sync_conn.exec_driver_sql(ddl)
                logger.info("Миграция: добавлен столбец %s.%s", table.name, col.name)


async def init_db() -> None:
    """Создаёт/мигрирует таблицы и гарантирует наличие строки состояния вотчера."""
    async with engine.begin() as conn:
        await conn.run_sync(_migrate)
    async with SessionLocal() as session:
        state = await session.get(WatcherState, 1)
        if state is None:
            session.add(WatcherState(id=1))
            await session.commit()


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Контекстный менеджер сессии с авто-commit/rollback."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_watcher_state(session: AsyncSession) -> WatcherState:
    state = await session.get(WatcherState, 1)
    if state is None:
        state = WatcherState(id=1)
        session.add(state)
        await session.flush()
    return state


async def listing_exists(session: AsyncSession, avito_id: str) -> bool:
    from app.models import Listing

    res = await session.execute(select(Listing.id).where(Listing.avito_id == avito_id))
    return res.first() is not None
