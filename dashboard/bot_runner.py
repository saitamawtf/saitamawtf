# dashboard/bot_runner.py
"""
Manages the bot lifecycle in a background thread and bridges events
(trades, logs) back to the async FastAPI layer via queues.
"""
import asyncio
import logging
import queue
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Optional

# Make the project root importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import Config, TradingMode
from exchange.phemex_client import PhemexClient
from strategy.orb_classic import ORBClassic
from strategy.orb_fvg import ORBFVG


# ── In-memory log ring-buffer (last 300 lines) ─────────────────────────────────
LOG_BUFFER: Deque[Dict[str, str]] = deque(maxlen=300)
_event_queue: queue.Queue = queue.Queue()   # cross-thread events → async handler


class QueueLogHandler(logging.Handler):
    """Captures log records and pushes them to the shared buffer + event queue."""

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "ts": datetime.utcnow().strftime("%H:%M:%S"),
            "level": record.levelname,
            "name": record.name,
            "msg": self.format(record),
        }
        LOG_BUFFER.append(entry)
        try:
            _event_queue.put_nowait({"type": "log", "data": entry})
        except queue.Full:
            pass


# ── Tracking wrapper around PhemexClient ──────────────────────────────────────

class TrackingClient(PhemexClient):
    """
    Subclass of PhemexClient that intercepts place_order and
    has_open_position calls to record trade lifecycle events.
    """

    def __init__(self, config: Config, runner: "BotRunner"):
        super().__init__(config)
        self._runner = runner
        self._open_trade_id: Optional[int] = None
        self._last_entry: Optional[float] = None
        self._last_sl: Optional[float] = None
        self._last_tp: Optional[float] = None
        self._last_direction: Optional[str] = None

    def place_order(
        self,
        direction: str,
        contracts: int,
        sl: float,
        tp: float,
    ) -> dict:
        result = super().place_order(direction, contracts, sl, tp)

        # Cache levels so we can estimate PnL on close
        self._last_direction = direction
        self._last_sl = sl
        self._last_tp = tp
        self._last_entry = self.get_current_price()

        event = {
            "type": "trade_open",
            "data": {
                "timestamp": datetime.utcnow().isoformat(),
                "mode": self._runner.current_mode,
                "symbol": self.config.SYMBOL,
                "direction": direction,
                "entry": self._last_entry,
                "sl": sl,
                "tp": tp,
                "contracts": contracts,
                "risk_usd": self.config.RISK_PER_TRADE_USD,
            },
        }
        _event_queue.put_nowait(event)
        return result

    def has_open_position(self) -> bool:
        had_open = self._last_entry is not None
        still_open = super().has_open_position()

        # Position just closed
        if had_open and not still_open and self._open_trade_id is not None:
            try:
                exit_price = self.get_current_price()
                pnl, status = self._estimate_result(exit_price)
            except Exception:
                exit_price = None
                pnl = None
                status = "closed"

            _event_queue.put_nowait(
                {
                    "type": "trade_close",
                    "data": {
                        "trade_id": self._open_trade_id,
                        "status": status,
                        "exit_price": exit_price,
                        "pnl_usd": pnl,
                    },
                }
            )
            # Reset
            self._last_entry = None
            self._open_trade_id = None

        return still_open

    def _estimate_result(self, exit_price: float):
        """Rough PnL estimate based on entry/sl/tp proximity."""
        if not self._last_entry or not self._last_sl or not self._last_tp:
            return None, "closed"

        sl_dist = abs(self._last_entry - self._last_sl)
        tp_dist = abs(self._last_entry - self._last_tp)
        exit_dist_sl = abs(exit_price - self._last_sl)
        exit_dist_tp = abs(exit_price - self._last_tp)

        if exit_dist_tp < exit_dist_sl:
            status = "tp_hit"
            pnl = self.config.RISK_PER_TRADE_USD * (tp_dist / sl_dist)
        else:
            status = "sl_hit"
            pnl = -self.config.RISK_PER_TRADE_USD

        return round(pnl, 2), status


# ── Bot runner ──────────────────────────────────────────────────────────────────

class BotRunner:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.current_mode: str = "classic"
        self.current_state: str = "stopped"
        self.config: Optional[Config] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Logging setup
        self._log_handler = QueueLogHandler()
        self._log_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s",
                              datefmt="%H:%M:%S")
        )
        logging.getLogger().addHandler(self._log_handler)
        logging.getLogger().setLevel(logging.INFO)

    # ── Public API ──────────────────────────────────────────────────────

    def start(self, config: Config, loop: asyncio.AbstractEventLoop) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Bot already running")

        self.config = config
        self.current_mode = config.MODE.value
        self._loop = loop
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run_loop,
            name="BotThread",
            daemon=True,
        )
        self._thread.start()
        self.current_state = "running"

        # Start async event consumer
        asyncio.run_coroutine_threadsafe(self._consume_events(), loop)

    def stop(self) -> None:
        self._stop_event.set()
        self.current_state = "stopped"

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_logs(self) -> list:
        return list(LOG_BUFFER)

    # ── Internal ─────────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        from exchange.phemex_client import PhemexClient

        client = TrackingClient(self.config, self)

        if self.config.MODE == TradingMode.CLASSIC:
            strategy = ORBClassic(self.config, client)
        else:
            strategy = ORBFVG(self.config, client)

        log = logging.getLogger("BotRunner")
        log.info(f"Bot iniciado — Modo: {self.config.MODE.value.upper()} | "
                 f"Symbol: {self.config.SYMBOL}")

        while not self._stop_event.is_set():
            try:
                now = datetime.now(timezone.utc)
                if self.config.NY_OPEN_HOUR - 1 <= now.hour <= self.config.SESSION_END_HOUR:
                    strategy.run_cycle(now)
                self._stop_event.wait(timeout=30)
            except Exception as exc:
                log.error(f"Error en ciclo: {exc}", exc_info=True)
                self._stop_event.wait(timeout=60)

        log.info("Bot detenido.")
        self.current_state = "stopped"

    async def _consume_events(self) -> None:
        """Async task that reads from the thread-safe queue and persists to DB."""
        from dashboard.database import insert_trade, close_trade

        open_id: Optional[int] = None

        while self.is_running or not _event_queue.empty():
            try:
                event = _event_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.5)
                continue

            if event["type"] == "trade_open":
                open_id = await insert_trade(event["data"])
                # Give the tracking client the DB id
                if self._thread and hasattr(self._thread, "_target"):
                    pass  # id passed via event data below

                # Store id in the event queue for close correlation
                _event_queue.put_nowait({"type": "_set_trade_id", "id": open_id})

            elif event["type"] == "_set_trade_id":
                open_id = event["id"]
                # Propagate to client via runner attribute
                self._current_open_trade_id = open_id

            elif event["type"] == "trade_close":
                tid = event["data"].get("trade_id") or open_id
                if tid:
                    await close_trade(
                        trade_id=tid,
                        status=event["data"]["status"],
                        exit_price=event["data"].get("exit_price"),
                        pnl_usd=event["data"].get("pnl_usd"),
                    )

            await asyncio.sleep(0)


# Singleton
bot_runner = BotRunner()
