# risk/risk_manager.py


class RiskManager:
    def __init__(self, config):
        self.config = config

    def calculate_position_size(
        self,
        entry: float,
        sl: float,
        risk_usd: float,
    ) -> int:
        """
        Calcula el número de contratos dado el riesgo máximo en USD.

        Fórmula base:
            btc_size  = risk_usd / |entry - sl|
            contracts = btc_size / 0.001   (1 contrato Phemex linear = 0.001 BTC)

        Retorna el número de contratos redondeado hacia abajo,
        con un mínimo de 1.

        Nota: para BTCUSDT linear perpetual en Phemex el valor mínimo
        de contrato y el multiplicador pueden cambiar; verificar la
        documentación de Phemex antes de usar en producción.
        """
        sl_distance = abs(entry - sl)

        if sl_distance == 0:
            raise ValueError("SL distance cannot be zero")

        btc_size = risk_usd / sl_distance
        # 1 contrato Phemex BTCUSDT linear ≈ 0.001 BTC
        contracts = int(btc_size / 0.001)
        return max(1, contracts)

    def validate_trade(
        self,
        entry: float,
        sl: float,
        tp: float,
        direction: str,
    ) -> bool:
        """
        Verifica que los niveles del trade sean coherentes con la dirección.

        Long : SL < entry < TP
        Short: TP < entry < SL
        """
        if direction == "long":
            return sl < entry < tp
        elif direction == "short":
            return tp < entry < sl
        return False

    def get_classic_levels(self, orb_range, direction: str) -> dict:
        """
        Calcula entry, SL y TP para el modo CLÁSICO.

        Entry : precio de breakout (high/low del rango ORB)
        SL    : SL_STDEV_CLASSIC × tamaño del rango dentro del rango
        TP    : TP_STDEV_CLASSIC × tamaño del rango fuera del rango
        """
        sl = orb_range.sl_classic(direction, self.config.SL_STDEV_CLASSIC)
        tp = orb_range.tp_classic(direction, self.config.TP_STDEV_CLASSIC)

        entry = orb_range.high if direction == "long" else orb_range.low

        return {
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "direction": direction,
        }
