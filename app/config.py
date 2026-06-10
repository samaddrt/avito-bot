"""Конфигурация приложения. Все секреты и настройки берутся из .env (никогда из кода)."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Корень проекта и путь к данным
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    """Настройки, загружаемые из переменных окружения / .env."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    bot_token: str = Field(default="", alias="BOT_TOKEN")
    owner_telegram_id: int = Field(default=0, alias="OWNER_TELEGRAM_ID")

    # Gemini
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")

    # Web / Mini App
    web_host: str = Field(default="0.0.0.0", alias="WEB_HOST")
    web_port: int = Field(default=8000, alias="WEB_PORT")
    webapp_url: str = Field(default="", alias="WEBAPP_URL")

    # Watcher
    watcher_enabled: bool = Field(default=True, alias="WATCHER_ENABLED")
    watch_interval_min: int = Field(default=180, alias="WATCH_INTERVAL_MIN")
    watch_interval_max: int = Field(default=300, alias="WATCH_INTERVAL_MAX")
    watch_max_detail_per_run: int = Field(default=4, alias="WATCH_MAX_DETAIL_PER_RUN")
    watch_headless: bool = Field(default=True, alias="WATCH_HEADLESS")

    # Экономика
    min_profit_rub: int = Field(default=3000, alias="MIN_PROFIT_RUB")
    min_margin_pct: float = Field(default=12.0, alias="MIN_MARGIN_PCT")
    # Базовые расходы на сделку (дорога/комиссия/мелкий ремонт), вычитаются из прибыли
    default_cost_rub: int = Field(default=700, alias="DEFAULT_COST_RUB")
    # Период сканирования напоминаний, минуты
    reminder_scan_min: int = Field(default=60, alias="REMINDER_SCAN_MIN")
    # Типичная скидка «выгодного» объявления от рынка (для подбора по бюджету), %
    opportunity_discount_pct: float = Field(default=22.0, alias="OPPORTUNITY_DISCOUNT_PCT")

    # Производные пути
    @property
    def db_path(self) -> Path:
        return DATA_DIR / "solomoney.db"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def db_url_sync(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def pricebook_path(self) -> Path:
        return DATA_DIR / "pricebook.json"

    @property
    def searches_path(self) -> Path:
        return DATA_DIR / "searches.json"

    @property
    def backups_dir(self) -> Path:
        d = DATA_DIR / "backups"
        d.mkdir(exist_ok=True)
        return d

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def bot_enabled(self) -> bool:
        return bool(self.bot_token and self.owner_telegram_id)


settings = Settings()
