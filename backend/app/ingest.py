"""Ingesta: consulta las APIs, evalúa las reglas y guarda el resultado."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .clients import UpstreamError, fetch_forecasts, fetch_precip_grid, fetch_quakes
from .config import Settings
from .db import Database
from .grid import GRID_POINTS
from .locations import LOCATIONS
from .models import PrecipGrid
from .rules import evaluate_location, evaluate_quakes, sort_alerts

logger = logging.getLogger("centinela.ingest")

PRECIP_META_KEY = "precip_grid"


@dataclass
class IngestResult:
    ok: bool
    forecasts: int
    quakes: int
    alerts: int
    errors: list[str] = field(default_factory=list)


async def run_ingest(
    db: Database,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """Cada fuente falla de forma independiente: si una cae, se conservan sus datos anteriores."""
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat(timespec="seconds")
    db.set_meta("last_attempt_at", now_iso)

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=20, headers={"User-Agent": settings.user_agent})

    errors: list[str] = []
    successes = 0
    try:
        try:
            forecasts = await fetch_forecasts(client, LOCATIONS)
            db.save_snapshots(forecasts, now_iso)
            successes += 1
        except UpstreamError as exc:
            errors.append(f"open-meteo: {exc}")
            logger.warning("Open-Meteo falló: %s", exc)

        try:
            quakes = await fetch_quakes(client, now=now)
            db.replace_quakes(quakes)
            successes += 1
        except UpstreamError as exc:
            errors.append(f"usgs: {exc}")
            logger.warning("USGS falló: %s", exc)
    finally:
        if owns_client:
            await client.aclose()

    # Las alertas siempre se recalculan con lo mejor que haya en la base.
    snapshots = db.get_snapshots()
    alerts = []
    for loc in LOCATIONS:
        snap = snapshots.get(loc.id)
        if snap is not None:
            alerts.extend(evaluate_location(loc, snap.current.time, snap.hourly))
    alerts.extend(evaluate_quakes(db.get_quakes(), LOCATIONS, now_ms=int(now.timestamp() * 1000)))
    alerts = sort_alerts(alerts)
    db.replace_alerts(alerts)

    if successes:
        db.set_meta("last_ingest_at", now_iso)
    db.set_meta("last_error", "; ".join(errors))

    result = IngestResult(
        ok=not errors,
        forecasts=len(snapshots),
        quakes=len(db.get_quakes()),
        alerts=len(alerts),
        errors=errors,
    )
    logger.info("Ingesta: %s", result)
    return result


# --- grilla de precipitación prevista -------------------------------------------------------------
# Va aparte de `run_ingest`: son ~200 puntos que Open-Meteo cuenta uno a uno contra su límite diario,
# así que se renueva cada `precip_ttl_s` (1 h) aunque la ingesta general corra cada 15 minutos.
def load_precip(db: Database) -> PrecipGrid | None:
    raw = db.get_meta(PRECIP_META_KEY)
    if not raw:
        return None
    try:
        return PrecipGrid.model_validate_json(raw)
    except ValueError:
        return None


def precip_is_due(db: Database, settings: Settings, now: datetime) -> bool:
    grid = load_precip(db)
    if grid is None:
        return True
    try:
        age = (now - datetime.fromisoformat(grid.fetched_at)).total_seconds()
    except ValueError:
        return True
    return age >= settings.precip_ttl_s


async def run_precip_ingest(
    db: Database,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> bool:
    """Renueva la grilla si venció. Devuelve True si la actualizó; un fallo conserva la anterior."""
    now = now or datetime.now(timezone.utc)
    if not precip_is_due(db, settings, now):
        return False

    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=20, headers={"User-Agent": settings.user_agent})
    try:
        grid = await fetch_precip_grid(client, GRID_POINTS, now=now)
    except UpstreamError as exc:
        db.set_meta("precip_error", str(exc))
        logger.warning("Grilla de precipitación falló: %s", exc)
        return False
    finally:
        if owns_client:
            await client.aclose()

    db.set_meta(PRECIP_META_KEY, grid.model_dump_json())
    db.set_meta("precip_error", "")
    logger.info("Grilla de precipitación actualizada: %d celdas", len(grid.cells))
    return True