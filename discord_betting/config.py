"""
Configuration loader.
All settings come from environment variables (loaded from .env if present).
"""

import os
import logging
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            f"Copy .env.example → .env and fill in the values."
        )
    return value


def _int_list(name: str, default: str = "") -> list[int]:
    raw = os.getenv(name, default).strip()
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _str_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default).strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class Config:
    # Discord
    discord_token: str
    discord_channel_ids: list[int]

    # Filters (empty list = no filter applied)
    discord_filter_authors: list[str] = field(default_factory=list)
    discord_filter_role_ids: list[int] = field(default_factory=list)

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/bets.log"


def load_config() -> Config:
    cfg = Config(
        discord_token=_require("DISCORD_TOKEN"),
        discord_channel_ids=_int_list("DISCORD_CHANNEL_IDS"),
        discord_filter_authors=_str_list("DISCORD_FILTER_AUTHORS"),
        discord_filter_role_ids=_int_list("DISCORD_FILTER_ROLE_IDS"),
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_require("TELEGRAM_CHAT_ID"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_file=os.getenv("LOG_FILE", "logs/bets.log"),
    )

    if not cfg.discord_channel_ids:
        raise EnvironmentError(
            "DISCORD_CHANNEL_IDS must contain at least one channel ID."
        )

    return cfg


def setup_logging(level: str, log_file: str) -> None:
    import pathlib

    pathlib.Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    handlers.append(file_handler)

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=fmt,
        handlers=handlers,
    )
