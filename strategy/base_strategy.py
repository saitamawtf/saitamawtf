# strategy/base_strategy.py
import logging
from abc import ABC, abstractmethod
from datetime import datetime


class BaseStrategy(ABC):
    """
    Clase base para todas las estrategias ORB.

    Implementa el ciclo de vida común:
      WAITING_RANGE → WATCHING_BREAKOUT → [WAITING_RETEST →] IN_TRADE → DONE
    y la lógica de reset diario.
    """

    # Estados posibles del bot
    STATE_WAITING_RANGE = "WAITING_RANGE"
    STATE_WATCHING_BREAKOUT = "WATCHING_BREAKOUT"
    STATE_WAITING_RETEST = "WAITING_RETEST"
    STATE_IN_TRADE = "IN_TRADE"
    STATE_DONE = "DONE"

    def __init__(self, config, client):
        self.config = config
        self.client = client
        self.state = self.STATE_WAITING_RANGE
        self.log = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def run_cycle(self, current_time: datetime) -> None:
        """Ejecuta un ciclo de evaluación de la estrategia."""

    @abstractmethod
    def _reset(self) -> None:
        """Reinicia el estado interno para el siguiente día de trading."""

    def _should_reset(self, current_time: datetime) -> bool:
        """
        Retorna True si es el momento de preparar el bot para el
        siguiente día (una hora antes de la apertura NY).
        """
        return (
            current_time.hour == self.config.NY_OPEN_HOUR - 1
            and self.state == self.STATE_DONE
        )
