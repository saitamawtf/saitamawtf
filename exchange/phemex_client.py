# exchange/phemex_client.py
import ccxt
import pandas as pd
from typing import List, Optional


class PhemexClient:
    """
    Wrapper sobre ccxt.phemex para operaciones con futuros perpetuos.

    Notas de uso:
      - defaultType='swap' activa el modo de derivados perpetuos.
      - set_sandbox_mode(True) redirige las peticiones al testnet de Phemex.
      - Los parámetros stopLossPrice / takeProfitPrice se envían en params
        del create_order; Phemex los soporta en el mismo request.
    """

    def __init__(self, config):
        self.config = config
        self.exchange = ccxt.phemex(
            {
                "apiKey": config.API_KEY,
                "secret": config.API_SECRET,
                "enableRateLimit": True,
                "options": {
                    "defaultType": "swap",  # Perpetual futures
                },
            }
        )

        if config.TESTNET:
            self.exchange.set_sandbox_mode(True)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def get_ohlcv(self, timeframe: str, limit: int = 100) -> pd.DataFrame:
        """
        Obtiene velas OHLCV y las retorna como DataFrame indexado por
        timestamp UTC.
        """
        ohlcv = self.exchange.fetch_ohlcv(
            self.config.SYMBOL,
            timeframe=timeframe,
            limit=limit,
        )
        df = pd.DataFrame(
            ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        return df

    def get_current_price(self) -> float:
        """Retorna el último precio negociado."""
        ticker = self.exchange.fetch_ticker(self.config.SYMBOL)
        return float(ticker["last"])

    # ------------------------------------------------------------------
    # Order management
    # ------------------------------------------------------------------

    def place_order(
        self,
        direction: str,
        contracts: int,
        sl: float,
        tp: float,
    ) -> dict:
        """
        Coloca una orden de mercado con SL y TP adjuntos.

        direction : "long" | "short"
        contracts : número de contratos (1 contrato = 0.001 BTC en BTCUSDT linear)
        sl        : precio de stop loss
        tp        : precio de take profit
        """
        side = "buy" if direction == "long" else "sell"

        params = {
            "stopLossPrice": sl,
            "takeProfitPrice": tp,
            "timeInForce": "GoodTillCancel",
        }

        order = self.exchange.create_order(
            symbol=self.config.SYMBOL,
            type="market",
            side=side,
            amount=contracts,
            params=params,
        )
        return order

    def close_all_positions(self) -> None:
        """
        Cierra todas las posiciones abiertas para el símbolo configurado
        usando órdenes de mercado con reduceOnly=True.
        """
        positions = self.exchange.fetch_positions([self.config.SYMBOL])
        for pos in positions:
            size = float(pos.get("contracts", 0))
            if size > 0:
                close_side = "sell" if pos["side"] == "long" else "buy"
                self.exchange.create_order(
                    symbol=self.config.SYMBOL,
                    type="market",
                    side=close_side,
                    amount=size,
                    params={"reduceOnly": True},
                )

    def has_open_position(self) -> bool:
        """Retorna True si hay alguna posición abierta en el símbolo."""
        positions = self.exchange.fetch_positions([self.config.SYMBOL])
        return any(float(p.get("contracts", 0)) > 0 for p in positions)
