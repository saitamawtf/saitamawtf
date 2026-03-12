# strategy/orb_fvg.py
from datetime import datetime
from typing import Optional

from indicators.fvg_detector import FairValueGap, FVGDetector
from indicators.opening_range import OpeningRangeDetector
from risk.risk_manager import RiskManager
from strategy.base_strategy import BaseStrategy


class ORBFVG(BaseStrategy):
    """
    Modo 2: ORB + FVG Retest
    ========================
    Flujo:
      1. Igual al modo clásico: esperar rango m15 y buscar breakout m5.
      2. El breakout debe crear al menos un FVG en m5 (en la misma dirección).
      3. NO entrar en el breakout directamente.
      4. Esperar que el precio retroceda y toque el FVG (retest).
      5. Entry: al tocar el borde del FVG más cercano al precio.
      6. SL    : open de la vela m5 que creó el FVG.
      7. TP    : RR 1:2 fijo desde el entry.
      8. Bad day: igual al modo clásico.
    """

    def __init__(self, config, client):
        super().__init__(config, client)
        self.orb_detector = OpeningRangeDetector(config)
        self.fvg_detector = FVGDetector(config)
        self.risk = RiskManager(config)
        self.active_fvg: Optional[FairValueGap] = None

    def run_cycle(self, current_time: datetime) -> None:

        # ── 1. Esperar rango ───────────────────────────────────────────
        if self.state == self.STATE_WAITING_RANGE:
            range_ready = (
                current_time.hour == self.config.ORB_END_HOUR
                and current_time.minute >= self.config.ORB_END_MIN
            )
            if range_ready:
                candles_m15 = self.client.get_ohlcv(
                    self.config.TIMEFRAME_ORB, limit=10
                )
                orb = self.orb_detector.calculate_range(candles_m15)
                if orb:
                    self.log.info(
                        f"Rango ORB definido — High: {orb.high:.2f} | "
                        f"Low: {orb.low:.2f} | Size: {orb.size:.2f}"
                    )
                    self.state = self.STATE_WATCHING_BREAKOUT

        # ── 2. Esperar breakout + FVG ──────────────────────────────────
        elif self.state == self.STATE_WATCHING_BREAKOUT:

            if self.orb_detector.is_bad_day(current_time):
                self.log.info(
                    "Bad day: sin breakout antes de las 12:00 PM NY. Skip del día."
                )
                self.state = self.STATE_DONE
                return

            candles_m5 = self.client.get_ohlcv(
                self.config.TIMEFRAME_ENTRY, limit=30
            )
            direction = self.orb_detector.check_breakout(candles_m5)

            if direction:
                self.log.info(
                    f"Breakout {direction.upper()} detectado. Buscando FVG..."
                )
                # Buscar FVGs en las últimas 10 velas m5 (zona del breakout)
                fvgs = self.fvg_detector.scan_fvgs(
                    candles_m5.tail(10),
                    direction_filter=direction,
                )
                if fvgs:
                    # El FVG más reciente es el más relevante
                    self.active_fvg = fvgs[-1]
                    self.log.info(
                        f"FVG encontrado — Gap: [{self.active_fvg.gap_low:.2f} – "
                        f"{self.active_fvg.gap_high:.2f}] | "
                        f"SL referencia: {self.active_fvg.candle2_open:.2f}"
                    )
                    self.state = self.STATE_WAITING_RETEST
                else:
                    self.log.info(
                        "Breakout sin FVG asociado. Esperando siguiente vela..."
                    )
                    # Se mantiene en WATCHING_BREAKOUT para intentar en el
                    # próximo ciclo (puede aparecer un FVG en velas siguientes)

        # ── 3. Esperar retest del FVG ──────────────────────────────────
        elif self.state == self.STATE_WAITING_RETEST:

            current_price = self.client.get_current_price()

            if self.fvg_detector.check_retest(current_price, self.active_fvg):
                self.log.info(
                    f"Retest del FVG detectado — Precio actual: {current_price:.2f}"
                )
                self._execute_trade()
                self.state = self.STATE_IN_TRADE

        # ── 4. Monitorear trade ────────────────────────────────────────
        elif self.state == self.STATE_IN_TRADE:
            if not self.client.has_open_position():
                self.log.info("Trade FVG cerrado (SL o TP alcanzado).")
                self.state = self.STATE_DONE

        # ── 5. Fin del día → esperar reset ────────────────────────────
        elif self.state == self.STATE_DONE:
            if self._should_reset(current_time):
                self._reset()

    def _execute_trade(self) -> None:
        levels = self.fvg_detector.get_fvg_entry_levels(
            self.active_fvg,
            rr=self.config.RR_RATIO,
        )

        size = self.risk.calculate_position_size(
            entry=levels["entry"],
            sl=levels["sl"],
            risk_usd=self.config.RISK_PER_TRADE_USD,
        )

        self.log.info(
            f"Orden FVG — Entry: {levels['entry']:.2f} | "
            f"SL: {levels['sl']:.2f} | TP: {levels['tp']:.2f} | "
            f"Contratos: {size}"
        )

        if self.risk.validate_trade(
            levels["entry"], levels["sl"], levels["tp"], levels["direction"]
        ):
            order = self.client.place_order(
                levels["direction"], size, levels["sl"], levels["tp"]
            )
            self.log.info(f"Orden FVG ejecutada — ID: {order['id']}")
            self.active_fvg.retested = True
        else:
            self.log.error(
                "Trade FVG inválido: niveles incoherentes. Operación cancelada."
            )

    def _reset(self) -> None:
        self.log.info("Reset diario completado. Esperando nueva sesión NY.")
        self.orb_detector.range = None
        self.active_fvg = None
        self.state = self.STATE_WAITING_RANGE
