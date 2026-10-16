"""Ingesta: consulta las APIs, evalúa las reglas y guarda el resultado."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .clients import UpstreamError, fetch_forecasts, fetch_quakes
from .config import Settings
from .db import Database
from .locations import LOCATIONS
from .rules import evaluate_location, evaluate_quakes, sort_alerts

logger = logging.getLogger("centinela.ingest")


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
