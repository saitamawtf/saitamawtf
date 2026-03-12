# config.py
from dataclasses import dataclass, field
from enum import Enum


class TradingMode(Enum):
    CLASSIC = "classic"  # ORB tradicional
    FVG = "fvg"          # ORB + FVG retest


@dataclass
class Config:
    # --- Credenciales ---
    API_KEY: str = "TU_API_KEY"
    API_SECRET: str = "TU_API_SECRET"
    TESTNET: bool = True  # True para testnet primero

    # --- Instrumento ---
    SYMBOL: str = "BTCUSDT"
    TIMEFRAME_ORB: str = "15m"    # Para definir el rango
    TIMEFRAME_ENTRY: str = "5m"   # Para breakout y FVG

    # --- Horarios NY (UTC) ---
    # 9:30 AM NY = 14:30 UTC (sin horario de verano: 13:30 UTC)
    NY_OPEN_HOUR: int = 14
    NY_OPEN_MIN: int = 30
    # 9:45 AM NY = 14:45 UTC (cierre del rango ORB)
    ORB_END_HOUR: int = 14
    ORB_END_MIN: int = 45
    # 12:00 PM NY = 17:00 UTC (límite para bad day)
    BAD_DAY_HOUR: int = 17
    BAD_DAY_MIN: int = 0
    # Cierre de sesión de trading
    SESSION_END_HOUR: int = 21

    # --- Modo de trading ---
    MODE: TradingMode = TradingMode.CLASSIC

    # --- Risk Management ---
    RISK_PER_TRADE_USD: float = 50.0  # Riesgo en USD por trade
    RR_RATIO: float = 2.0             # Ratio riesgo:recompensa

    # --- Fibonacci / STDEV levels ---
    # El rango m15 equivale a 1 STDEV
    # SL clásico: 0.5 STDEV dentro del rango desde el punto de breakout
    # TP clásico: 2 STDEV fuera del rango
    SL_STDEV_CLASSIC: float = 0.5
    TP_STDEV_CLASSIC: float = 2.0
