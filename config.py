"""Runtime configuration loaded from environment variables or .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _csv(name: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in os.getenv(name, "").split(",") if p.strip())


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    return int(raw) if raw else None


@dataclass(frozen=True)
class Config:
    city: str
    target_districts: tuple[str, ...]
    min_price: int
    max_price: int | None
    max_commission: int | None
    max_move_in_cost: int | None

    disallowed_floors: tuple[int, ...]
    disallowed_keywords: tuple[str, ...]

    telegram_bot_token: str
    allowed_user_ids: tuple[int, ...]

    gemini_api_key: str
    gemini_model: str

    cian_region_id: str
    avito_city_slug: str
    yandex_city_slug: str

    db_path: Path
    scan_interval_sec: int


@lru_cache(maxsize=1)
def get_config() -> Config:
    if load_dotenv:
        load_dotenv()

    min_price = int(os.getenv("MIN_PRICE", "0"))
    max_price = _optional_int("MAX_PRICE")
    if max_price is not None and max_price < min_price:
        raise ValueError("MAX_PRICE must be >= MIN_PRICE")

    root_dir = Path(__file__).resolve().parent
    raw_db = os.getenv("DB_PATH", "data/flats.db").strip()
    db_path = Path(raw_db) if Path(raw_db).is_absolute() else (root_dir / raw_db)

    return Config(
        city=os.getenv("CITY", "Москва"),
        target_districts=_csv("TARGET_DISTRICTS"),
        min_price=min_price,
        max_price=max_price,
        max_commission=_optional_int("MAX_COMMISSION"),
        max_move_in_cost=_optional_int("MAX_MOVE_IN_COST"),
        disallowed_floors=tuple(int(f) for f in _csv("DISALLOWED_FLOORS")),
        disallowed_keywords=tuple(k.lower() for k in _csv("DISALLOWED_KEYWORDS")),
        telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
        allowed_user_ids=tuple(int(u) for u in _csv("ALLOWED_USER_IDS")),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        cian_region_id=os.getenv("CIAN_REGION_ID", "1"),
        avito_city_slug=os.getenv("AVITO_CITY_SLUG", "moskva"),
        yandex_city_slug=os.getenv("YANDEX_CITY_SLUG", "moskva"),
        db_path=db_path.resolve(),
        scan_interval_sec=int(os.getenv("SCAN_INTERVAL_SEC", "300")),
    )
