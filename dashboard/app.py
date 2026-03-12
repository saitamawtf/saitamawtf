# dashboard/app.py
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import Config, TradingMode
from dashboard.bot_runner import LOG_BUFFER, bot_runner
from dashboard.database import get_all_trades, get_stats, init_db

# ── App setup ──────────────────────────────────────────────────────────────────
app = FastAPI(title="ORB Bot Dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.on_event("startup")
async def startup() -> None:
    await init_db()


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Bot control ────────────────────────────────────────────────────────────────

@app.post("/api/bot/start")
async def start_bot(request: Request):
    body: Dict[str, Any] = await request.json()

    mode = TradingMode.CLASSIC if body.get("mode") == "classic" else TradingMode.FVG

    try:
        config = Config(
            API_KEY=body["api_key"],
            API_SECRET=body["api_secret"],
            TESTNET=body.get("testnet", True),
            SYMBOL=body.get("symbol", "BTCUSDT"),
            MODE=mode,
            RISK_PER_TRADE_USD=float(body.get("risk_usd", 50)),
            RR_RATIO=float(body.get("multiplier", 2.0)),
            SL_STDEV_CLASSIC=float(body.get("sl_stdev", 0.5)),
            TP_STDEV_CLASSIC=float(body.get("multiplier", 2.0)),
        )
    except (KeyError, ValueError) as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=422)

    if bot_runner.is_running:
        return JSONResponse({"ok": False, "error": "Bot ya está corriendo"}, status_code=409)

    loop = asyncio.get_event_loop()
    try:
        bot_runner.start(config, loop)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    return {"ok": True, "state": "running"}


@app.post("/api/bot/stop")
async def stop_bot():
    bot_runner.stop()
    return {"ok": True, "state": "stopped"}


@app.get("/api/bot/status")
async def bot_status():
    return {
        "running": bot_runner.is_running,
        "state": "running" if bot_runner.is_running else "stopped",
        "mode": bot_runner.current_mode,
    }


# ── Live logs via SSE ─────────────────────────────────────────────────────────

@app.get("/api/logs/stream")
async def log_stream():
    """
    Server-Sent Events endpoint.
    Sends a snapshot of recent logs on connect, then polls for new ones.
    """
    async def event_generator():
        sent = 0
        # Initial flush
        logs = list(LOG_BUFFER)
        for entry in logs:
            yield f"data: {json.dumps(entry)}\n\n"
        sent = len(logs)

        while True:
            await asyncio.sleep(1)
            current = list(LOG_BUFFER)
            new = current[sent:]
            for entry in new:
                yield f"data: {json.dumps(entry)}\n\n"
            sent = len(current)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/logs")
async def get_logs():
    return list(LOG_BUFFER)


# ── Trade data ────────────────────────────────────────────────────────────────

@app.get("/api/trades")
async def trades():
    return await get_all_trades()


@app.get("/api/stats")
async def stats():
    return await get_stats()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=8000, reload=False)
