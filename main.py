# main.py
import logging
import time
from datetime import datetime, timezone

from config import Config, TradingMode
from exchange.phemex_client import PhemexClient
from strategy.orb_classic import ORBClassic
from strategy.orb_fvg import ORBFVG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

POLL_INTERVAL_SECONDS = 30   # Ciclo cada 30 s para no perder señales m5
ERROR_SLEEP_SECONDS = 60     # Espera tras error inesperado


def build_strategy(config: Config, client: PhemexClient):
    """Instancia la estrategia correcta según el modo configurado."""
    if config.MODE == TradingMode.CLASSIC:
        logging.info("Modo seleccionado: ORB Clásico")
        return ORBClassic(config, client)
    else:
        logging.info("Modo seleccionado: ORB + FVG Retest")
        return ORBFVG(config, client)


def is_active_session(now: datetime, config: Config) -> bool:
    """
    Retorna True si el momento actual está dentro de la ventana de
    trading relevante (desde una hora antes de la apertura NY hasta
    el cierre de sesión configurado).
    """
    return config.NY_OPEN_HOUR - 1 <= now.hour <= config.SESSION_END_HOUR


def main() -> None:
    # ──────────────────────────────────────────────────────────────────
    # Configuración principal
    # Ajusta API_KEY, API_SECRET y MODE antes de usar en producción.
    # Mantén TESTNET=True hasta validar la lógica completamente.
    # ──────────────────────────────────────────────────────────────────
    config = Config(
        API_KEY="TU_API_KEY",
        API_SECRET="TU_API_SECRET",
        TESTNET=True,
        SYMBOL="BTCUSDT",
        MODE=TradingMode.FVG,         # TradingMode.CLASSIC o TradingMode.FVG
        RISK_PER_TRADE_USD=50.0,
        RR_RATIO=2.0,
        SL_STDEV_CLASSIC=0.5,
        TP_STDEV_CLASSIC=2.0,
    )

    client = PhemexClient(config)
    strategy = build_strategy(config, client)

    logging.info("Bot ORB iniciado. Esperando sesión NY...")

    while True:
        try:
            now = datetime.now(timezone.utc)

            if is_active_session(now, config):
                strategy.run_cycle(now)

            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logging.info("Bot detenido manualmente (KeyboardInterrupt).")
            break

        except Exception as exc:
            logging.error(
                f"Error inesperado en ciclo principal: {exc}",
                exc_info=True,
            )
            time.sleep(ERROR_SLEEP_SECONDS)


if __name__ == "__main__":
    main()
