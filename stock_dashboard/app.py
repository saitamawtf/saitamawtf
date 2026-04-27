"""Dashboard de insights de acciones — FastAPI en puerto 8001.

Uso: python -m stock_dashboard.app
"""

import asyncio
import logging
import sys
from pathlib import Path

import pytz
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.schedulers.base import STATE_STOPPED
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stock_dashboard.ai_analyzer import analyze_all
from stock_dashboard.cache import (
    get_next_refresh_iso,
    is_cache_fresh,
    load_cache,
    save_cache,
)
from stock_dashboard.data_fetcher import fetch_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PDT = pytz.timezone("America/Los_Angeles")
scheduler = AsyncIOScheduler(timezone=PDT)

app = FastAPI(title="Stock Insights Dashboard — META & NVDA")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

_refresh_lock = asyncio.Lock()


async def run_refresh() -> None:
    """Obtiene datos de mercado y ejecuta análisis de IA; guarda resultado en caché."""
    async with _refresh_lock:
        logger.info("Iniciando ciclo de actualización de datos...")
        try:
            raw = await asyncio.to_thread(fetch_all)
            insights = await asyncio.to_thread(analyze_all, raw)
            data = {**raw, "insights": insights, "next_refresh_at": get_next_refresh_iso()}
            save_cache(data)
            logger.info("Actualización completada exitosamente.")
        except Exception as exc:
            logger.error("Error en ciclo de actualización: %s", exc, exc_info=True)


@app.on_event("startup")
async def startup() -> None:
    # Actualización diaria a las 9:00 AM PDT
    scheduler.add_job(
        run_refresh,
        CronTrigger(hour=9, minute=0, timezone=PDT),
        id="daily_refresh",
        replace_existing=True,
    )
    scheduler.start()

    # Si el caché está desactualizado, actualizar en segundo plano al arrancar
    if not is_cache_fresh():
        logger.info("Caché desactualizado; iniciando actualización inicial...")
        asyncio.create_task(run_refresh())
    else:
        logger.info("Caché fresco; no se requiere actualización al arrancar.")


@app.on_event("shutdown")
async def shutdown() -> None:
    if scheduler.state != STATE_STOPPED:
        scheduler.shutdown(wait=False)


# ── Rutas ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "stock_index.html")


@app.get("/api/stock-data")
async def get_stock_data() -> JSONResponse:
    data = load_cache()
    if not data:
        return JSONResponse(
            {"error": "Datos aún no disponibles. La actualización está en progreso..."},
            status_code=503,
        )
    # Asegurar que next_refresh_at esté siempre fresco
    data["next_refresh_at"] = get_next_refresh_iso()
    return JSONResponse(data)


@app.post("/api/refresh")
async def manual_refresh() -> dict:
    if _refresh_lock.locked():
        return {"ok": False, "message": "Ya hay una actualización en progreso."}
    asyncio.create_task(run_refresh())
    return {"ok": True, "message": "Actualización iniciada en segundo plano."}


if __name__ == "__main__":
    uvicorn.run(
        "stock_dashboard.app:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info",
    )
