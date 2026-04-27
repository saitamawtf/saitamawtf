# CLAUDE.md — ORB Trading Bot

This file provides context and conventions for AI assistants working in this repository.

## Project Overview

This is an **Opening Range Breakout (ORB) automated trading bot** for BTC perpetual futures on the **Phemex** exchange. It implements two algorithmic strategies based on the New York market open (9:30 AM ET):

- **Classic ORB**: Enters on a breakout of the 15-minute opening range. SL is set 0.5 standard deviations inside the range; TP is set 2 standard deviations beyond the breakout.
- **FVG (Fair Value Gap) Retest**: Waits for the breakout candle to create a Fair Value Gap, then enters when price retests (pulls back into) that gap, with SL at the impulse candle open and TP at a fixed R:R ratio.

The bot runs only during the NY session (roughly 13:30–21:00 UTC) and skips the day if no breakout occurs by 12:00 PM NY (17:00 UTC — the "bad day" threshold).

There are **three execution modes**:
1. **CLI / standalone** — `python main.py` (no UI)
2. **ORB web dashboard** — `python -m dashboard.app` (FastAPI on port 8000)
3. **Stock insights dashboard** — `python -m stock_dashboard.app` (FastAPI on port 8001) — agrega noticias, datos de mercado y análisis de IA (Claude Sonnet 4.6) para META y NVDA con actualización automática a las 9:00 AM PDT

---

## Repository Structure

```
saitamawtf/
├── config.py                    # Central Config dataclass + TradingMode enum
├── main.py                      # CLI entry point (standalone bot loop)
├── requirements.txt             # Python dependencies
├── .env.example                 # Template for required environment vars
├── exchange/
│   └── phemex_client.py         # CCXT wrapper for Phemex perpetuals
├── strategy/
│   ├── base_strategy.py         # Abstract BaseStrategy + state machine constants
│   ├── orb_classic.py           # Classic ORB implementation
│   └── orb_fvg.py               # FVG retest implementation
├── indicators/
│   ├── opening_range.py         # OpeningRange dataclass + StdDev level helpers
│   └── fvg_detector.py          # FairValueGap dataclass + scan/retest logic
├── risk/
│   └── risk_manager.py          # Position sizing + trade validation
├── dashboard/
│   ├── app.py                   # FastAPI app: routes + SSE log streaming
│   ├── bot_runner.py            # BotRunner (threading bridge) + TrackingClient
│   ├── database.py              # Async SQLite CRUD via aiosqlite
│   ├── trades.db                # SQLite database (git-ignored, created at runtime)
│   └── templates/
│       └── index.html           # Single-page UI (Tailwind CSS + Chart.js via CDN)
├── stock_dashboard/             # Dashboard de insights bursátiles (META & NVDA)
│   ├── app.py                   # FastAPI en puerto 8001 + APScheduler diario 9 AM PDT
│   ├── data_fetcher.py          # yfinance (precio/analistas) + RSS (noticias)
│   ├── ai_analyzer.py           # Claude Sonnet 4.6 con prompt caching + JSON estructurado
│   ├── cache.py                 # Caché en JSON (frescura: <1h o post 9AM PDT)
│   ├── stock_cache.json         # Caché generado en runtime (git-ignored)
│   └── templates/
│       └── stock_index.html     # SPA con Tailwind + Chart.js sparklines
└── utils/                       # Utility module (currently empty)
```

---

## Running the Bot

### Install dependencies

```bash
pip install -r requirements.txt
```

### CLI mode (no UI)

Edit credentials directly in `main.py` (the `Config(...)` call near line 46), then:

```bash
python main.py
```

The bot polls every 30 seconds. Press `Ctrl+C` to stop.

### Dashboard mode (web UI)

```bash
python -m dashboard.app
# UI available at http://localhost:8000
```

From the browser, enter API credentials, choose mode, and click **Start**. Credentials are sent as JSON to `POST /api/bot/start` and are never persisted to disk.

### Environment

Copy `.env.example` to `.env` and fill in values. The `.env` file is git-ignored. Currently, `main.py` reads credentials from the hardcoded `Config(...)` call — there is no automatic `.env` loading (no `python-dotenv`). The dashboard accepts credentials via the API request body.

```
PHEMEX_API_KEY=your_key_here
PHEMEX_API_SECRET=your_secret_here
TESTNET=true
```

**Always start with `TESTNET=true`** to validate logic against the Phemex sandbox before trading real funds.

---

## Configuration (`config.py`)

All tuneable parameters live in the `Config` dataclass. Key fields:

| Field | Default | Description |
|-------|---------|-------------|
| `API_KEY` / `API_SECRET` | placeholder | Phemex credentials |
| `TESTNET` | `True` | Use Phemex sandbox |
| `SYMBOL` | `"BTCUSDT"` | Perpetual futures pair |
| `TIMEFRAME_ORB` | `"15m"` | Candle size for range definition |
| `TIMEFRAME_ENTRY` | `"5m"` | Candle size for entry signals |
| `NY_OPEN_HOUR/MIN` | `14:30 UTC` | NY market open (9:30 AM ET) |
| `ORB_END_HOUR/MIN` | `14:45 UTC` | End of 15-min opening range |
| `BAD_DAY_HOUR/MIN` | `17:00 UTC` | Deadline — skip day if no breakout |
| `SESSION_END_HOUR` | `21` | End of active trading session (UTC) |
| `MODE` | `TradingMode.CLASSIC` | Strategy to use |
| `RISK_PER_TRADE_USD` | `50.0` | USD risked per trade |
| `RR_RATIO` | `2.0` | Risk:Reward for FVG mode |
| `SL_STDEV_CLASSIC` | `0.5` | SL distance in range StdDevs (Classic) |
| `TP_STDEV_CLASSIC` | `2.0` | TP distance in range StdDevs (Classic) |

`TradingMode` is an enum with two values: `CLASSIC` and `FVG`.

---

## Strategy State Machine

Every strategy subclass inherits these states from `BaseStrategy`:

```
WAITING_RANGE → WATCHING_BREAKOUT → [WAITING_RETEST] → IN_TRADE → DONE
```

| State | Meaning |
|-------|---------|
| `WAITING_RANGE` | Before ORB close; collecting the 15m opening range |
| `WATCHING_BREAKOUT` | Range defined; watching for price to break out |
| `WAITING_RETEST` | (FVG only) Breakout formed a gap; waiting for price to retest it |
| `IN_TRADE` | Order placed; monitoring for SL/TP hit |
| `DONE` | Trade closed or bad-day skip; no more actions today |

Daily reset happens when `state == DONE` and `current_time.hour == NY_OPEN_HOUR - 1` (one hour before NY open). This transitions back to `WAITING_RANGE`.

---

## Architecture Details

### Exchange layer (`exchange/phemex_client.py`)

Wraps `ccxt.phemex` with perpetuals mode enabled. Key methods:
- `get_ohlcv(symbol, timeframe, limit)` → `pd.DataFrame`
- `get_current_price(symbol)` → `float`
- `place_order(symbol, side, contracts, sl, tp)` → order dict
- `close_all_positions(symbol)` — market close
- `has_open_position(symbol)` → `bool`

### Risk management (`risk/risk_manager.py`)

- `calculate_position_size(entry, sl, risk_usd)` → number of contracts (1 contract = 0.001 BTC)
- `validate_trade(direction, entry, sl, tp)` → `bool` — asserts price ordering is correct for the direction
- `get_classic_levels(orb, direction)` → `(sl, tp)` using StdDev multipliers

### Threading model (dashboard)

The dashboard runs FastAPI (async) in the main thread and the bot (sync) in a background `threading.Thread`. Communication uses:
- `queue.Queue` for events from bot thread → async FastAPI handler (for DB writes)
- `collections.deque(maxlen=300)` as `LOG_BUFFER` for SSE log streaming
- `QueueLogHandler` (Python `logging.Handler`) captures all bot logs into the deque and event queue

### Database (`dashboard/database.py`)

SQLite file at `dashboard/trades.db`. All functions are async via `aiosqlite`. The file is created automatically on startup.

---

## Dashboard API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves `index.html` |
| `POST` | `/api/bot/start` | Start bot with JSON config body |
| `POST` | `/api/bot/stop` | Stop running bot |
| `GET` | `/api/bot/status` | Returns `{running, state, mode}` |
| `GET` | `/api/logs` | Returns recent log buffer (up to 300 lines) |
| `GET` | `/api/logs/stream` | SSE stream of live logs |
| `GET` | `/api/trades` | All trades, newest first |
| `GET` | `/api/stats` | Aggregated stats (win rate, PnL, equity curve) |

`POST /api/bot/start` request body fields:

```json
{
  "api_key": "...",
  "api_secret": "...",
  "testnet": true,
  "symbol": "BTCUSDT",
  "mode": "classic",
  "risk_usd": 50,
  "multiplier": 2.0,
  "sl_stdev": 0.5
}
```

Error responses follow `{"ok": false, "error": "..."}` with HTTP 422 (validation), 409 (conflict), or 500.

---

## Database Schema

Table: `trades`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | Auto-increment |
| `timestamp` | TEXT | ISO format, UTC, trade open time |
| `mode` | TEXT | `"classic"` or `"fvg"` |
| `symbol` | TEXT | e.g. `"BTCUSDT"` |
| `direction` | TEXT | `"long"` or `"short"` |
| `entry` | REAL | Entry price |
| `sl` | REAL | Stop loss price |
| `tp` | REAL | Take profit price |
| `contracts` | INTEGER | Number of contracts traded |
| `risk_usd` | REAL | USD risked on this trade |
| `status` | TEXT | `"open"`, `"tp_hit"`, `"sl_hit"` |
| `exit_price` | REAL | Actual exit price (filled on close) |
| `pnl_usd` | REAL | Realized PnL in USD |
| `closed_at` | TEXT | ISO format, UTC, when trade closed |

---

## Code Conventions

### Language

- **Python 3** — no JavaScript build step, no npm
- Frontend assets (Tailwind CSS, Chart.js) are loaded from CDN in `index.html`

### Style

- **Indentation**: 4 spaces
- **Type hints**: Used consistently — always add type hints to new functions
- **Imports**: Standard library first, then third-party (ccxt, pandas, fastapi), then local (`from exchange... import ...`)
- **No linter config** is present — follow standard PEP 8
- `sys.path.insert(0, str(ROOT))` is used in `dashboard/app.py` to make the project root importable from subdirectories; replicate this pattern if adding new dashboard modules

### Naming

| Construct | Convention | Example |
|-----------|-----------|---------|
| Classes | PascalCase | `PhemexClient`, `ORBClassic`, `RiskManager` |
| Functions / methods | snake_case | `place_order()`, `check_breakout()` |
| Private methods | Leading underscore | `_execute_trade()`, `_reset()` |
| Constants | UPPER_SNAKE_CASE | `POLL_INTERVAL_SECONDS`, `STATE_IN_TRADE` |
| Variables | snake_case | `current_price`, `orb_range` |
| Enum members | UPPER_CASE | `TradingMode.CLASSIC` |

### Language of comments

Code comments and docstrings are in **Spanish** (the domain language of this project). Technical identifiers (class names, method names, variable names) are in English. Keep this convention when adding code.

### Logging

Use `logging.getLogger(self.__class__.__name__)` inside classes. At module level use `logging.info/error/warning`. Always pass `exc_info=True` when logging exceptions.

---

## Adding a New Strategy

1. Create `strategy/orb_mymode.py`
2. Subclass `BaseStrategy` from `strategy/base_strategy.py`
3. Implement the two abstract methods:
   - `run_cycle(self, current_time: datetime) -> None`
   - `_reset(self) -> None`
4. Add a new member to `TradingMode` in `config.py`
5. Add a branch in `build_strategy()` in `main.py`
6. Add the new mode to the dashboard's `POST /api/bot/start` parsing in `dashboard/app.py`

The strategy receives `self.config` (a `Config` instance) and `self.client` (a `PhemexClient` instance). Use `self.state` to track state machine transitions and `self.log` for logging.

---

## Testing

There is currently **no automated test suite**. Manual testing process:

1. Set `TESTNET=True` in config — this points CCXT to the Phemex sandbox
2. Run the bot in CLI mode or dashboard mode
3. Monitor logs for state machine transitions (WAITING_RANGE → WATCHING_BREAKOUT → ...)
4. Confirm orders appear in the Phemex testnet UI
5. Verify trade records are written to `dashboard/trades.db`

When adding new logic, test manually on testnet before enabling live trading.

---

## Key Constraints for AI Assistants

- **Never hardcode live API credentials** — always use `TESTNET=True` in example code and keep credentials in `.env` (which is git-ignored)
- **Do not modify the state machine flow** in `BaseStrategy` without understanding both `ORBClassic` and `ORBFVG` — they rely on the exact state constant strings
- **Contract sizing** — 1 contract = 0.001 BTC on Phemex. The `calculate_position_size()` method in `risk_manager.py` encodes this; do not change it without also updating `place_order()`
- **Time zones** — all times in the codebase are UTC. NY open is 14:30 UTC in summer (EDT) and 13:30 UTC in winter (EST). The config defaults to summer hours
- **Thread safety** — the bot runs in a background thread in dashboard mode. Do not call `async` functions from the bot thread directly; use the `queue.Queue` event pipeline already established in `bot_runner.py`
- **SQLite** — `dashboard/trades.db` is excluded from git (check `.gitignore`). Do not commit this file
- **No ORM** — database queries use raw SQL via `aiosqlite`. Keep this pattern; do not introduce SQLAlchemy or similar
