"""Пайплайн анализа объявления: распознавание → анализ → скоринг → сообщения.

Связывает Gemini-слой и детерминированный scoring. Возвращает готовый объект,
который сохраняется в БД и показывается в боте/Mini App.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.ai import gemini, prompts
from app.core import scoring
from app.core.scoring import ScoredDeal
from app.schemas import (
    DealAnalysis,
    ListingParse,
    NegotiationMessages,
    ResaleDraft,
)

logger = logging.getLogger(__name__)


@dataclass
class AnalyzedListing:
    """Полный результат анализа одного объявления."""

    raw_text: str
    parse: ListingParse
    analysis: DealAnalysis
    scored: ScoredDeal
    negotiation: NegotiationMessages | None = None

    @property
    def title(self) -> str:
        return self.parse.model_name or (self.raw_text[:60] if self.raw_text else "Товар")


async def analyze_listing(raw_text: str, *, with_negotiation: bool = True) -> AnalyzedListing:
    """Главная точка входа: из сырого текста объявления делает готовый анализ."""
    if not raw_text or len(raw_text.strip()) < 8:
        raise ValueError("Слишком короткий текст для анализа")

    # 1) Распознаём товар.
    parse = await gemini.generate_structured(
        system_instruction=prompts.SYSTEM_PARSER,
        prompt=prompts.build_parse_prompt(raw_text),
        schema=ListingParse,
        temperature=0.1,
    )

    parsed_hint = (
        f"Предварительно распознано: категория={parse.category}, модель={parse.model_name}, "
        f"конфигурация={parse.config}, состояние={parse.condition}."
    )

    # 2) Полный анализ выгодности/риска.
    analysis = await gemini.generate_structured(
        system_instruction=prompts.SYSTEM_ANALYST,
        prompt=prompts.build_analysis_prompt(raw_text, parsed_hint),
        schema=DealAnalysis,
        temperature=0.4,
    )

    # 3) Детерминированный скоринг поверх Gemini.
    scored = scoring.score(
        analysis,
        raw_text=raw_text,
        category=parse.category,
        model_name=parse.model_name,
        seller_price=parse.seller_price or None,
    )

    result = AnalyzedListing(raw_text=raw_text, parse=parse, analysis=analysis, scored=scored)

    # 4) Сообщения для торга — только если сделка не отбракована.
    if with_negotiation and scored.verdict in {"BUY_NOW", "NEGOTIATE", "WATCH"}:
        try:
            result.negotiation = await generate_negotiation(
                title=result.title,
                seller_price=parse.seller_price or scored.market_price,
                target_price=scored.target_buy_price,
                what_to_check=analysis.what_to_check,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось сгенерировать сообщения для торга: %s", exc)

    return result


async def generate_negotiation(*, title: str, seller_price: int, target_price: int,
                               what_to_check: list[str]) -> NegotiationMessages:
    return await gemini.generate_structured(
        system_instruction=prompts.SYSTEM_NEGOTIATOR,
        prompt=prompts.build_negotiation_prompt(title, seller_price, target_price, what_to_check),
        schema=NegotiationMessages,
        temperature=0.7,
    )


async def generate_resale(*, title: str, model_name: str, buy_price: int,
                          market_price: int, quick_sale_price: int) -> ResaleDraft:
    return await gemini.generate_structured(
        system_instruction=prompts.SYSTEM_RESALE,
        prompt=prompts.build_resale_prompt(
            title, model_name, buy_price, market_price, quick_sale_price
        ),
        schema=ResaleDraft,
        temperature=0.6,
    )
