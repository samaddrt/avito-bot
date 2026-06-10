"""ORM-модели: сделки, объявления, анализы, события, состояние вотчера."""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DealStatus(str, enum.Enum):
    """Пайплайн сделки."""

    new = "new"            # найдено/проанализировано, ещё ничего не делали
    contacted = "contacted"      # написали продавцу
    negotiating = "negotiating"  # идёт торг / диалог
    bought = "bought"            # купили
    listed = "listed"            # выставили на перепродажу
    sold = "sold"                # продали
    watching = "watching"        # наблюдаем
    skipped = "skipped"          # пропустили


class Verdict(str, enum.Enum):
    BUY_NOW = "BUY_NOW"
    NEGOTIATE = "NEGOTIATE"
    WATCH = "WATCH"
    SKIP = "SKIP"
    HIGH_RISK = "HIGH_RISK"


class Listing(Base):
    """Сырое объявление (из вотчера или ручного ввода). Дедуп по avito_id."""

    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("avito_id", name="uq_listing_avito_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    avito_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual | playwright
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, default="")
    seller_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deal: Mapped["Deal | None"] = relationship(back_populates="listing", uselist=False)


class Deal(Base):
    """Сделка — основная сущность, которую ведём по пайплайну."""

    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id"), nullable=True)

    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus), default=DealStatus.new, index=True
    )
    verdict: Mapped[Verdict | None] = mapped_column(Enum(Verdict), nullable=True, index=True)

    # Товар
    title: Mapped[str] = mapped_column(String(512), default="")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Экономика
    seller_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    market_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quick_sale_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_buy_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_costs: Mapped[int] = mapped_column(Integer, default=0)   # дорога/комиссия/ремонт (прогноз)
    expected_profit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ЧИСТАЯ ожидаемая прибыль
    gross_profit: Mapped[int | None] = mapped_column(Integer, nullable=True)     # до вычета расходов
    margin_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Торг / договорённости
    offer_price: Mapped[int | None] = mapped_column(Integer, nullable=True)   # что я предложил
    agreed_price: Mapped[int | None] = mapped_column(Integer, nullable=True)  # о чём договорились
    seller_replied: Mapped[bool] = mapped_column(Boolean, default=False)

    # Перепродажа
    resale_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resale_min_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_drops: Mapped[int] = mapped_column(Integer, default=0)

    # Фактические расходы по сделке
    extra_costs: Mapped[int] = mapped_column(Integer, default=0)
    costs_note: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Оценки
    liquidity: Mapped[str | None] = mapped_column(String(16), nullable=True)  # high/medium/low
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)     # 0..100
    hotness: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    days_to_sell_est: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Факт (заполняется при закрытии)
    actual_buy_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_sell_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bought_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    listed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sold_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    next_action: Mapped[str | None] = mapped_column(String(256), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    pushed: Mapped[bool] = mapped_column(Boolean, default=False)  # был ли пуш в Telegram

    # Напоминания
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    listing: Mapped[Listing | None] = relationship(back_populates="deal")
    analysis: Mapped["Analysis | None"] = relationship(
        back_populates="deal", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def actual_profit(self) -> int | None:
        """Фактическая ЧИСТАЯ прибыль = продажа − покупка − расходы."""
        if self.actual_buy_price is not None and self.actual_sell_price is not None:
            return self.actual_sell_price - self.actual_buy_price - (self.extra_costs or 0)
        return None

    @property
    def invested(self) -> int | None:
        """Вложено в сделку (для расчёта ROI и замороженного капитала)."""
        base = self.actual_buy_price or self.agreed_price or self.target_buy_price
        if base is None:
            return None
        return base + (self.extra_costs or 0)

    @property
    def roi_pct(self) -> float | None:
        p, inv = self.actual_profit, self.invested
        if p is not None and inv:
            return round(p / inv * 100, 1)
        return None


class Analysis(Base):
    """Полный структурированный вывод Gemini + scoring по сделке (JSON-поля)."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), unique=True)

    why_good: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_to_check: Mapped[list | None] = mapped_column(JSON, nullable=True)
    questions_to_seller: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scam_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    negotiation_messages: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # tone -> text
    meeting_checklist: Mapped[list | None] = mapped_column(JSON, nullable=True)
    resale_draft: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_gemini: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deal: Mapped[Deal] = relationship(back_populates="analysis")


class EventLog(Base):
    """Журнал решений и событий — всё проверяемо."""

    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(64))  # analyze, verdict, push, status_change, watch...
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WatcherState(Base):
    """Состояние мониторинга (одна строка, id=1): пауза, бэкофф и т.п."""

    __tablename__ = "watcher_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    backoff_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    backoff_level: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    runs_total: Mapped[int] = mapped_column(Integer, default=0)
    listings_seen: Mapped[int] = mapped_column(Integer, default=0)
