"""Módulo de caché en disco para datos de acciones."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytz

logger = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).parent / "stock_cache.json"
PDT = pytz.timezone("America/Los_Angeles")


def load_cache() -> Optional[dict[str, Any]]:
    """Carga los datos del archivo de caché."""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception as exc:
        logger.error("Error leyendo caché: %s", exc, exc_info=True)
        return None


def save_cache(data: dict[str, Any]) -> None:
    """Guarda los datos en el archivo de caché."""
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as exc:
        logger.error("Error guardando caché: %s", exc, exc_info=True)


def is_cache_fresh() -> bool:
    """
    Verifica si el caché es válido.
    El caché es fresco si fue generado hoy después de las 9 AM PDT,
    o si tiene menos de 1 hora de antigüedad.
    """
    cached = load_cache()
    if not cached or "fetched_at" not in cached:
        return False

    try:
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        now_utc = datetime.now(timezone.utc)

        # Fresco si tiene menos de 1 hora
        age_seconds = (now_utc - fetched_at).total_seconds()
        if age_seconds < 3600:
            return True

        # Fresco si fue hoy después de las 9 AM PDT
        fetched_local = fetched_at.astimezone(PDT)
        now_local = now_utc.astimezone(PDT)
        return (
            fetched_local.date() == now_local.date()
            and fetched_local.hour >= 9
        )
    except Exception as exc:
        logger.error("Error evaluando frescura del caché: %s", exc, exc_info=True)
        return False


def get_next_refresh_iso() -> str:
    """Devuelve el timestamp ISO de la próxima actualización (9 AM PDT)."""
    from datetime import timedelta
    now_pdt = datetime.now(PDT)
    next_refresh = now_pdt.replace(hour=9, minute=0, second=0, microsecond=0)
    if now_pdt >= next_refresh:
        next_refresh += timedelta(days=1)
    return next_refresh.isoformat()
