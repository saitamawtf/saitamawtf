"""
Telegram sender: formats BetResult objects into pretty messages and sends them.
Uses python-telegram-bot in async mode.
"""

import asyncio
import logging
from datetime import datetime

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

from parser.bet_parser import BetResult

logger = logging.getLogger(__name__)

# Sport → emoji mapping
_SPORT_EMOJI: dict[str, str] = {
    "NBA": "🏀",
    "MLB": "⚾",
    "NFL": "🏈",
    "NHL": "🏒",
    "NCAAB": "🏀",
    "NCAAF": "🏈",
    "Soccer": "⚽",
    "Unknown": "🎲",
}

_MAX_RETRIES = 3
_RETRY_DELAYS = [2, 4, 8]  # seconds


class TelegramSender:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot = Bot(token=bot_token)
        self._chat_id = chat_id

    async def send_bet(
        self,
        bet: BetResult,
        hardrock_url: str,
        received_at: datetime | None = None,
    ) -> bool:
        """
        Format and send a bet alert to Telegram.
        Returns True on success, False after all retries fail.
        """
        received_at = received_at or datetime.now()
        text = self._format_message(bet, hardrock_url, received_at)
        return await self._send_with_retry(text)

    async def send_raw(
        self,
        raw_text: str,
        hardrock_url: str,
        received_at: datetime | None = None,
    ) -> bool:
        """
        Send a raw (unparsed) message alert — used as fallback when parsing fails.
        """
        received_at = received_at or datetime.now()
        time_str = received_at.strftime("%I:%M %p")
        text = (
            "⚠️ *Nueva Apuesta \\(no parseada\\)*\n"
            f"📋 `{self._escape(raw_text)}`\n"
            f"🔗 [Buscar en Hard Rock]({hardrock_url})\n"
            f"⏰ Recibido: {time_str}"
        )
        return await self._send_with_retry(text)

    # ── Formatting ────────────────────────────────────────────────────────────

    def _format_message(
        self, bet: BetResult, url: str, received_at: datetime
    ) -> str:
        time_str = received_at.strftime("%I:%M %p")
        sport = bet.sport or "Unknown"
        emoji = _SPORT_EMOJI.get(sport, "🎲")

        # Sport / teams line
        if bet.teams:
            teams_str = " vs ".join(bet.teams[:2])
            sport_line = f"{emoji} {sport} \\| {self._escape(teams_str)}"
        else:
            sport_line = f"{emoji} {sport}"

        # Bet type detail line
        bet_detail = self._format_bet_detail(bet)

        lines = [
            "🎯 *Nueva Apuesta*",
            f"📋 `{self._escape(bet.raw)}`",
            sport_line,
            bet_detail,
            f"🔗 [Abrir en Hard Rock]({url})",
            f"⏰ Recibido: {time_str}",
        ]

        # Parlay legs
        if bet.is_parlay and bet.legs:
            lines.append("")
            lines.append(f"🔀 *Parlay — {len(bet.legs)} legs:*")
            for i, leg in enumerate(bet.legs, 1):
                leg_detail = self._format_leg_detail(leg)
                lines.append(f"  {i}\\. {self._escape(leg_detail)}")

        return "\n".join(lines)

    def _format_bet_detail(self, bet: BetResult) -> str:
        if bet.bet_type == "spread":
            line_str = f"{bet.line:+.1f}" if bet.line is not None else "?"
            odds_str = f" \\({bet.odds:+d}\\)" if bet.odds is not None else ""
            return f"📊 Spread: {line_str}{odds_str}"
        elif bet.bet_type == "over_under":
            side = "Over" if (bet.line or 0) >= 0 else "Under"
            odds_str = f" \\({bet.odds:+d}\\)" if bet.odds is not None else ""
            return f"📊 {side}: {bet.line}{odds_str}"
        elif bet.bet_type == "moneyline":
            odds_str = f"{bet.odds:+d}" if bet.odds is not None else "?"
            return f"📊 Moneyline: {odds_str}"
        elif bet.bet_type == "parlay":
            return f"📊 Parlay \\({len(bet.legs)} legs\\)"
        return ""

    def _format_leg_detail(self, leg) -> str:
        team = leg.teams[0] if leg.teams else "?"
        if leg.bet_type == "spread":
            line = f"{leg.line:+.1f}" if leg.line is not None else "?"
            odds = f" ({leg.odds:+d})" if leg.odds is not None else ""
            return f"{team} {line}{odds}"
        elif leg.bet_type == "over_under":
            side = "O" if (leg.line or 0) >= 0 else "U"
            odds = f" ({leg.odds:+d})" if leg.odds is not None else ""
            return f"{side}{leg.line} {' vs '.join(leg.teams[:2])}{odds}"
        elif leg.bet_type == "moneyline":
            odds = f"{leg.odds:+d}" if leg.odds is not None else "?"
            return f"ML {team} {odds}"
        return leg.raw

    @staticmethod
    def _escape(text: str) -> str:
        """Escape special chars for Telegram MarkdownV2."""
        special = r"_*[]()~`>#+-=|{}.!"
        for ch in special:
            text = text.replace(ch, f"\\{ch}")
        return text

    # ── Sending with retry ────────────────────────────────────────────────────

    async def _send_with_retry(self, text: str) -> bool:
        for attempt, delay in enumerate(
            [0] + _RETRY_DELAYS, start=1
        ):
            if delay:
                await asyncio.sleep(delay)
            try:
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    disable_web_page_preview=False,
                )
                return True
            except TelegramError as exc:
                logger.warning(
                    "Telegram send failed (attempt %d/%d): %s",
                    attempt,
                    _MAX_RETRIES + 1,
                    exc,
                )

        logger.error("Telegram send failed after %d attempts.", _MAX_RETRIES + 1)
        return False
