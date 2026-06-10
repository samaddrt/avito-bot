"""Pydantic-схемы. Часть из них передаётся Gemini как response_schema — модель
обязана вернуть строго этот JSON и ничего лишнего (никакой «болтовни»)."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class VerdictEnum(str, Enum):
    BUY_NOW = "BUY_NOW"
    NEGOTIATE = "NEGOTIATE"
    WATCH = "WATCH"
    SKIP = "SKIP"
    HIGH_RISK = "HIGH_RISK"


class LiquidityEnum(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


# --------- Парсинг кривого объявления ---------
class ListingParse(BaseModel):
    """Распознавание товара по сырому тексту объявления."""

    category: str = Field(description="Категория из каталога (см. список в запросе) или 'other'")
    model_name: str = Field(description="Конкретная модель, напр. 'PS5 Slim Digital', 'MacBook Air M2 8/256', 'iPhone 14 128GB'")
    config: str = Field(default="", description="Объём памяти/RAM/SSD/версия, если есть")
    condition: str = Field(default="", description="Состояние: новый / как новый / б/у / на запчасти / неизвестно")
    completeness: str = Field(default="", description="Комплект: коробка, чек, зарядка, доп.геймпады и т.п.")
    seller_price: int = Field(default=0, description="Цена продавца в рублях, 0 если не указана")
    city: str = Field(default="", description="Город, если указан")
    listing_quality_flags: list[str] = Field(
        default_factory=list,
        description="Признаки 'кривого' объявления: плохое фото, мутное описание, опечатки в названии, заниженная/непонятная цена",
    )
    is_target_category: bool = Field(description="True если товар входит в фокус-категории (PS5/MacBook Air/iPhone)")


# --------- Полный анализ сделки ---------
class DealAnalysis(BaseModel):
    """Структурированный анализ выгодности и риска. Это совещательный вывод Gemini;
    финальный вердикт пересчитывает scoring.py."""

    market_price: int = Field(description="Реальная рыночная цена товара, ₽")
    quick_sale_price: int = Field(description="Цена быстрой перепродажи (за 1-3 дня), ₽")
    expected_buy_price: int = Field(description="Реалистичная цель покупки после торга, ₽")
    profit: int = Field(description="Ожидаемая прибыль = quick_sale_price - expected_buy_price, ₽")
    margin_pct: float = Field(description="Маржа в процентах от цены покупки")
    liquidity: LiquidityEnum = Field(description="Ликвидность товара")
    days_to_sell_est: int = Field(description="Оценка срока продажи в днях")
    risk_score: int = Field(ge=0, le=100, description="Риск 0 (безопасно) .. 100 (явный скам)")
    scam_flags: list[str] = Field(default_factory=list, description="Конкретные признаки риска/скама")
    why_good: str = Field(description="Короткое объяснение, почему сделка хорошая или плохая (1-3 предложения)")
    what_to_check: list[str] = Field(default_factory=list, description="Что проверить перед/при покупке")
    questions_to_seller: list[str] = Field(default_factory=list, description="Вопросы продавцу для отсева скама")
    meeting_checklist: list[str] = Field(default_factory=list, description="Чек-лист проверки товара на встрече под эту категорию")
    verdict: VerdictEnum = Field(description="Совещательный вердикт Gemini")


# --------- Сообщения для торга (разные тоны) ---------
class NegotiationMessages(BaseModel):
    polite: str = Field(description="Вежливый торг, уверенный покупатель, без давления и обмана")
    firm: str = Field(description="Более жёсткий торг с обоснованием цены, корректно")
    quick_meet: str = Field(description="Готов приехать сегодня за наличные при адекватной цене")


# --------- Черновик объявления для перепродажи ---------
class ResaleDraft(BaseModel):
    title: str = Field(description="Цепляющий заголовок объявления")
    description: str = Field(description="Продающее описание, честное, структурированное")
    price: int = Field(description="Стартовая цена продажи, ₽")
    min_price: int = Field(description="Минимальная цена, ниже которой продавать не стоит, ₽")
    selling_points: list[str] = Field(default_factory=list, description="Аргументы для покупателя")
    faq: list[str] = Field(default_factory=list, description="Ответы на частые вопросы покупателей")
    price_drop_strategy: str = Field(description="Стратегия снижения цены, если не продаётся (напр. -5% через 5 дней)")
