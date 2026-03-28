"""
Entry point for the Discord → Hard Rock Betting Bot.

Usage:
    python main.py

Environment:
    Copy .env.example → .env and fill in all required values.
"""

import logging

from config import load_config, setup_logging
from discord_bot import BettingBot

logger = logging.getLogger(__name__)


def main() -> None:
    config = load_config()
    setup_logging(config.log_level, config.log_file)

    logger.info("Starting Discord Betting Bot")
    logger.info(
        "Monitoring %d channel(s): %s",
        len(config.discord_channel_ids),
        config.discord_channel_ids,
    )
    if config.discord_filter_authors:
        logger.info("Filtering by authors: %s", config.discord_filter_authors)
    if config.discord_filter_role_ids:
        logger.info("Filtering by role IDs: %s", config.discord_filter_role_ids)

    bot = BettingBot(config)
    bot.run(config.discord_token, log_handler=None)  # log_handler=None: use our setup


if __name__ == "__main__":
    main()
