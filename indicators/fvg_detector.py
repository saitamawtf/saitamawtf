# indicators/fvg_detector.py
from dataclasses import dataclass
from typing import Optional, List
import pandas as pd


@dataclass
class FairValueGap:
    """
    Un FVG se forma con 3 velas consecutivas:
      - Vela 1: referencia
      - Vela 2: vela de impulso (la que CREA el gap)
      - Vela 3: confirma el gap

    FVG Alcista : low[vela3] > high[vela1]  → gap entre high[1] y low[3]
    FVG Bajista : high[vela3] < low[vela1]  → gap entre low[1] y high[3]

    El SL en modo FVG se coloca en el open de la vela 2.
    """
    gap_high: float        # Techo del gap
    gap_low: float         # Piso del gap
    direction: str         # "long" o "short"
    candle2_open: float    # Open de la vela de impulso (referencia para SL)
    candle2_index: int     # Índice en el DataFrame
    retested: bool = False
    active: bool = True

    @property
    def midpoint(self) -> float:
        return (self.gap_high + self.gap_low) / 2

    def is_in_gap(self, price: float) -> bool:
        """Verdadero si el precio está dentro del rango del FVG."""
        return self.gap_low <= price <= self.gap_high

    def sl_price(self) -> float:
        """SL en el open de la vela que creó el FVG."""
        return self.candle2_open


class FVGDetector:
    def __init__(self, config):
        self.config = config
        self.active_fvgs: List[FairValueGap] = []

    def scan_fvgs(
        self,
        candles: pd.DataFrame,
        direction_filter: Optional[str] = None,
    ) -> List[FairValueGap]:
        """
        Escanea el DataFrame buscando FVGs.

        direction_filter: "long" | "short" | None (ambos).
        Retorna lista de FairValueGap encontrados (puede ser vacía).
        """
        new_fvgs: List[FairValueGap] = []

        if len(candles) < 3:
            return new_fvgs

        for i in range(len(candles) - 2):
            c1 = candles.iloc[i]
            c2 = candles.iloc[i + 1]  # Vela de impulso
            c3 = candles.iloc[i + 2]

            # FVG Alcista: gap entre high[c1] y low[c3]
            if c3['low'] > c1['high'] and direction_filter in (None, "long"):
                fvg = FairValueGap(
                    gap_low=float(c1['high']),
                    gap_high=float(c3['low']),
                    direction="long",
                    candle2_open=float(c2['open']),
                    candle2_index=i + 1,
                )
                new_fvgs.append(fvg)

            # FVG Bajista: gap entre high[c3] y low[c1]
            elif c3['high'] < c1['low'] and direction_filter in (None, "short"):
                fvg = FairValueGap(
                    gap_low=float(c3['high']),
                    gap_high=float(c1['low']),
                    direction="short",
                    candle2_open=float(c2['open']),
                    candle2_index=i + 1,
                )
                new_fvgs.append(fvg)

        return new_fvgs

    def check_retest(self, current_price: float, fvg: FairValueGap) -> bool:
        """
        Verifica si el precio está retestando el FVG.

        Para long : el precio retrocedió hasta tocar la zona del gap.
        Para short: el precio rebotó hasta tocar la zona del gap.

        Retorna True si el precio está dentro del gap y el FVG aún está activo.
        """
        if not fvg.active or fvg.retested:
            return False

        return fvg.is_in_gap(current_price)

    def get_fvg_entry_levels(
        self, fvg: FairValueGap, rr: float = 2.0
    ) -> dict:
        """
        Calcula entry, SL y TP para un trade basado en FVG.

        Entry : borde del gap más cercano al precio de retest.
        SL    : open de la vela que creó el FVG.
        TP    : RR fijo 1:rr desde el entry.
        """
        sl = fvg.sl_price()

        if fvg.direction == "long":
            entry = fvg.gap_high        # Soporte en el borde superior del gap
            sl_distance = entry - sl
            tp = entry + (sl_distance * rr)
        else:
            entry = fvg.gap_low         # Resistencia en el borde inferior del gap
            sl_distance = sl - entry
            tp = entry - (sl_distance * rr)

        return {
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "sl_distance": sl_distance,
            "direction": fvg.direction,
        }
