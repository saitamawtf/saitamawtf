# strategy/orb_classic.py
from datetime import datetime

from indicators.opening_range import OpeningRangeDetector
from risk.risk_manager import RiskManager
from strategy.base_strategy import BaseStrategy


class ORBClassic(BaseStrategy):
    """
    Modo 1: ORB Tradicional
    ========================
    Flujo:
      1. Esperar que cierre la vela m15 de las 9:30 AM NY (9:45 AM).
      2. Registrar High y Low de esa vela como rango ORB.
      3. Monitorear velas m5 buscando una que cierre con el cuerpo
         entero fuera del rango (breakout).
      4. Entrar al mercado al precio de breakout.
      5. SL : SL_STDEV_CLASSIC × tamaño_rango dentro del rango.
      6. TP : TP_STDEV_CLASSIC × tamaño_rango fuera del rango.
      7. Si no hay breakout antes de las 12:00 PM NY → "bad day", skip.
    """

    def __init__(self, config, client):
        super().__init__(config, client)
        self.detector = OpeningRangeDetector(config)
        self.risk = RiskManager(config)

    def run_cycle(self, current_time: datetime) -> None:

        # ── 1. Esperar a que el rango esté disponible ──────────────────
        if self.state == self.STATE_WAITING_RANGE:
            range_ready = (
                current_time.hour == self.config.ORB_END_HOUR
                and current_time.minute >= self.config.ORB_END_MIN
            )
            if range_ready:
                candles_m15 = self.client.get_ohlcv(
                    self.config.TIMEFRAME_ORB, limit=10
                )
                orb = self.detector.calculate_range(candles_m15)
                if orb:
                    self.log.info(
                        f"Rango ORB definido — High: {orb.high:.2f} | "
                        f"Low: {orb.low:.2f} | Size: {orb.size:.2f}"
                    )
                    self.state = self.STATE_WATCHING_BREAKOUT

        # ── 2. Esperar breakout ────────────────────────────────────────
        elif self.state == self.STATE_WATCHING_BREAKOUT:

            if self.detector.is_bad_day(current_time):
                self.log.info(
                    "Bad day: sin breakout antes de las 12:00 PM NY. Skip del día."
                )
                self.state = self.STATE_DONE
                return

            candles_m5 = self.client.get_ohlcv(
                self.config.TIMEFRAME_ENTRY, limit=20
            )
            direction = self.detector.check_breakout(candles_m5)

            if direction:
                self.log.info(f"Breakout detectado — Dirección: {direction.upper()}")
                self._execute_trade(direction)
                self.state = self.STATE_IN_TRADE

        # ── 3. Monitorear trade ────────────────────────────────────────
        elif self.state == self.STATE_IN_TRADE:
            if not self.client.has_open_position():
                self.log.info("Trade cerrado (SL o TP alcanzado).")
                self.state = self.STATE_DONE

        # ── 4. Fin del día → esperar reset ────────────────────────────
        elif self.state == self.STATE_DONE:
            if self._should_reset(current_time):
                self._reset()

    def _execute_trade(self, direction: str) -> None:
        orb = self.detector.range
        levels = self.risk.get_classic_levels(orb, direction)

        size = self.risk.calculate_position_size(
            entry=levels["entry"],
            sl=levels["sl"],
            risk_usd=self.config.RISK_PER_TRADE_USD,
        )

        self.log.info(
            f"Orden CLASSIC — Entry: {levels['entry']:.2f} | "
            f"SL: {levels['sl']:.2f} | TP: {levels['tp']:.2f} | "
            f"Contratos: {size}"
        )

        if self.risk.validate_trade(
            levels["entry"], levels["sl"], levels["tp"], direction
        ):
            order = self.client.place_order(
                direction, size, levels["sl"], levels["tp"]
            )
            self.log.info(f"Orden ejecutada — ID: {order['id']}")
        else:
            self.log.error(
                "Trade inválido: niveles incoherentes. Operación cancelada."
            )

    def _reset(self) -> None:
        self.log.info("Reset diario completado. Esperando nueva sesión NY.")
        self.detector.range = None
        self.state = self.STATE_WAITING_RANGE
