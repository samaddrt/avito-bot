"""Тонкий клиент Gemini со структурированным выводом и ретраями.

Использует google-genai. Модель обязана вернуть JSON строго по Pydantic-схеме
(response_schema), поэтому мы получаем типизированный объект, а не текст.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TypeVar

from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_client = None


class GeminiError(RuntimeError):
    pass


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not settings.gemini_enabled:
        raise GeminiError(
            "GEMINI_API_KEY не задан. Добавь ключ в .env (получить: "
            "https://aistudio.google.com/app/apikey)"
        )
    try:
        from google import genai  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover
        raise GeminiError("Пакет google-genai не установлен: pip install google-genai") from exc

    _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


async def generate_structured(
    *,
    system_instruction: str,
    prompt: str,
    schema: type[T],
    temperature: float = 0.4,
    retries: int = 3,
) -> T:
    """Запрашивает у Gemini ответ строго по схеме и возвращает экземпляр модели."""
    from google.genai import types  # noqa: WPS433

    client = _get_client()
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
    )

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=config,
            )
            parsed = getattr(resp, "parsed", None)
            if isinstance(parsed, schema):
                return parsed
            # Фолбэк: распарсить текст вручную.
            if resp.text:
                return schema.model_validate_json(resp.text)
            raise GeminiError("Пустой ответ Gemini")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Gemini попытка %s/%s не удалась: %s", attempt, retries, exc)
            if attempt < retries:
                await asyncio.sleep(1.5 * attempt)
    raise GeminiError(f"Gemini не ответил после {retries} попыток: {last_exc}")
