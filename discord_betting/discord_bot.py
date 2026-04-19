"""
Discord bot: monitors specified channels for betting tips,
parses each message, builds a Hard Rock search link,
and forwards a formatted alert to Telegram.
"""

import json
import logging
from datetime import datetime, timezone

import discord

from config import Config
from parser.bet_parser import BetParser, BetResult
from link_builder import build_hardrock_url
from telegram_sender import TelegramSender

logger = logging.getLogger(__name__)


class BettingBot(discord.Client):
    """
    Discord client that listens for bet tip messages in configured channels
    and forwards them to Telegram with a Hard Rock search link.
    """

    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # Required: enable in Discord dev portal
        intents.guild_messages = True
        super().__init__(intents=intents)

        self._config = config
        self._parser = BetParser()
        self._telegram = TelegramSender(
            bot_token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
        self._channel_ids: set[int] = set(config.discord_channel_ids)
        self._filter_authors: set[str] = {
            a.lower() for a in config.discord_filter_authors
        }
        self._filter_role_ids: set[int] = set(config.discord_filter_role_ids)

    # ── Discord events ────────────────────────────────────────────────────────

    async def on_ready(self) -> None:
        logger.info(
            "Logged in as %s (ID: %s) | Monitoring channels: %s",
            self.user,
            self.user.id,
            list(self._channel_ids),
        )

    async def on_message(self, message: discord.Message) -> None:
        # Ignore own messages
        if message.author == self.user:
            return

        # Channel filter
        if message.channel.id not in self._channel_ids:
            return

        # Author filter (if configured)
        if self._filter_authors:
            author_name = message.author.name.lower()
            if author_name not in self._filter_authors:
                logger.debug(
                    "Skipping message from %s (not in author filter)", message.author
                )
                return

        # Role filter (if configured — only works in guild channels)
        if self._filter_role_ids and isinstance(message.author, discord.Member):
            author_role_ids = {r.id for r in message.author.roles}
            if not author_role_ids.intersection(self._filter_role_ids):
                logger.debug(
                    "Skipping message from %s (no matching role)", message.author
                )
                return

        raw = message.content.strip()
        if not raw:
            return

        logger.info(
            "New message | channel=%s | author=%s | content=%r",
            message.channel.name,
            message.author,
            raw[:120],
        )

        received_at = message.created_at.replace(tzinfo=timezone.utc).astimezone(
            tz=None
        )

        await self._handle_bet_message(raw, received_at)

    async def on_disconnect(self) -> None:
        logger.warning("Disconnected from Discord — will attempt to reconnect.")

    async def on_error(self, event: str, *args, **kwargs) -> None:
        logger.exception("Unhandled error in event '%s'", event)

    # ── Pipeline ──────────────────────────────────────────────────────────────

    async def _handle_bet_message(self, raw: str, received_at: datetime) -> None:
        bet: BetResult | None = self._parser.parse(raw)

        if bet is not None:
            url = build_hardrock_url(bet.teams)
            success = await self._telegram.send_bet(bet, url, received_at)
            self._log_entry(raw, bet, url, success)
        else:
            # Fallback: forward raw message with a generic search link
            logger.warning("Could not parse bet message: %r — sending raw.", raw[:120])
            # Build search with raw text (first 60 chars)
            url = build_hardrock_url([], extra=raw[:60])
            success = await self._telegram.send_raw(raw, url, received_at)
            self._log_entry(raw, None, url, success)

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log_entry(
        self,
        raw: str,
        bet: BetResult | None,
        url: str,
        success: bool,
    ) -> None:
        entry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "raw": raw,
            "parsed": (
                {
                    "bet_type": bet.bet_type,
                    "teams": bet.teams,
                    "sport": bet.sport,
                    "line": bet.line,
                    "odds": bet.odds,
                    "confidence": bet.confidence,
                    "is_parlay": bet.is_parlay,
                }
                if bet
                else None
            ),
            "hardrock_url": url,
            "telegram_sent": success,
        }
        logger.info("LOG_ENTRY %s", json.dumps(entry, ensure_ascii=False))
