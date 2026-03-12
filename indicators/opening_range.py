# indicators/opening_range.py
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class OpeningRange:
    high: float   # Techo del rango (high del m15)
    low: float    # Piso del rango (low del m15)
    size: float   # high - low = 1 STDEV
    broken: bool = False
    direction: Optional[str] = None  # "long" o "short"

    def stdev_level(self, multiplier: float, side: str) -> float:
        """
        Calcula niveles basados en desviaciones estándar.

        Para LONG (precio rompió hacia arriba):
          multiplier negativo  → proyección fuera del rango (TP)
          multiplier positivo  → dentro del rango (SL)

        Para SHORT (precio rompió hacia abajo): invertido.
        """
        if side == "long":
            return self.high + (multiplier * self.size)
        else:
            return self.low - (multiplier * self.size)

    def sl_classic(self, side: str, stdev: float = 0.5) -> float:
        """SL al 0.5 STDEV dentro del rango desde el punto de breakout."""
        if side == "long":
            # SL debajo del range high, 0.5 stdev hacia dentro del rango
            return self.high - (stdev * self.size)
        else:
            # SL encima del range low, 0.5 stdev hacia dentro del rango
            return self.low + (stdev * self.size)

    def tp_classic(self, side: str, stdev: float = 2.0) -> float:
        """TP a 2 STDEV en dirección del breakout."""
        if side == "long":
            return self.high + (stdev * self.size)
        else:
            return self.low - (stdev * self.size)


class OpeningRangeDetector:
    def __init__(self, config):
        self.config = config
        self.range: Optional[OpeningRange] = None

    def calculate_range(self, candles_m15: pd.DataFrame) -> Optional[OpeningRange]:
        """
        Recibe OHLCV del m15.
        Busca la vela de las 9:30 AM NY (14:30 UTC por defecto).
        """
        orb_candle = candles_m15[
            (candles_m15.index.hour == self.config.NY_OPEN_HOUR) &
            (candles_m15.index.minute == self.config.NY_OPEN_MIN)
        ]

        if orb_candle.empty:
            return None

        candle = orb_candle.iloc[0]
        high = float(candle['high'])
        low = float(candle['low'])

        self.range = OpeningRange(
            high=high,
            low=low,
            size=high - low,
        )
        return self.range

    def check_breakout(self, candles_m5: pd.DataFrame) -> Optional[str]:
        """
        Verifica si la última vela m5 cerró completamente fuera del rango.
        Requiere que el cuerpo entero (open y close) esté fuera del rango,
        no solo un wick.

        Retorna "long", "short" o None.
        """
        if not self.range:
            return None

        last = candles_m5.iloc[-1]
        last_close = float(last['close'])
        last_open = float(last['open'])

        body_high = max(last_close, last_open)
        body_low = min(last_close, last_open)

        if body_low > self.range.high:
            self.range.broken = True
            self.range.direction = "long"
            return "long"

        elif body_high < self.range.low:
            self.range.broken = True
            self.range.direction = "short"
            return "short"

        return None

    def is_bad_day(self, current_time) -> bool:
        """
        Si el rango está definido pero no hay breakout antes de las
        12:00 PM NY (17:00 UTC por defecto), el día se descarta.
        """
        if self.range and not self.range.broken:
            limit_passed = (
                current_time.hour > self.config.BAD_DAY_HOUR or
                (current_time.hour == self.config.BAD_DAY_HOUR and
                 current_time.minute >= self.config.BAD_DAY_MIN)
            )
            if limit_passed:
                return True
        return False
