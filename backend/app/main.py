"""API REST de Centinela (FastAPI).

Se ejecuta con:  uvicorn app.main:create_app --factory
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .db import Database
from .ingest import load_precip, run_ingest, run_precip_ingest
from .locations import LOCATIONS, LOCATIONS_BY_ID
from .models import (
    SEVERITY_RANK,
    Alert,
    AlertKind,
    ForecastResponse,
    LocationSummary,
    PrecipGrid,
    Quake,
    Severity,
    StatusResponse,
)
from .rules import describe_rules, max_severity

logger = logging.getLogger("centinela")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    db = Database(settings.db_path)
    db.init()
    lock = asyncio.Lock()  # evita ingestas simultáneas (scheduler + /api/refresh)

    async def ingest_once():
        async with lock:
            result = await run_ingest(db, settings)
            try:
                await run_precip_ingest(db, settings)  # no hace nada mientras la grilla siga vigente
            except Exception:  # noqa: BLE001 - la grilla nunca debe tumbar la ingesta general
                logger.exception("Falló la actualización de la precipitación prevista")
            return result

    async def scheduler() -> None:
        while True:
            try:
                await ingest_once()
            except Exception:  # noqa: BLE001 - el scheduler nunca debe morir
                logger.exception("Falló la ingesta programada")
            await asyncio.sleep(settings.ingest_interval_min * 60)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = asyncio.create_task(scheduler()) if settings.scheduler_enabled else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(
        title="Centinela API",
        version="1.0.0",
        description="Alertas de clima y sismos para Chile a partir de Open-Meteo y USGS.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        return StatusResponse(
            last_ingest_at=db.get_meta("last_ingest_at"),
            last_error=db.get_meta("last_error") or None,
            locations=len(LOCATIONS),
            alerts=len(db.get_alerts()),
            quakes=len(db.get_quakes()),
            interval_min=settings.ingest_interval_min,
        )

    @app.get("/api/rules")
    def rules() -> dict:
        return describe_rules()

    @app.get("/api/locations", response_model=list[LocationSummary])
    def list_locations() -> list[LocationSummary]:
        snapshots = db.get_snapshots()
        by_location: dict[str, list[Alert]] = defaultdict(list)
        for alert in db.get_alerts():
            if alert.location_id:
                by_location[alert.location_id].append(alert)
        summaries = []
        for loc in LOCATIONS:
            snap = snapshots.get(loc.id)
            alerts = by_location.get(loc.id, [])
            summaries.append(
                LocationSummary(
                    **loc.model_dump(),
                    current=snap.current if snap else None,
                    severity=max_severity(alerts),
                    alert_count=len(alerts),
                )
            )
        return summaries

    @app.get("/api/alerts", response_model=list[Alert])
    def list_alerts(min_severity: Severity | None = None, kind: AlertKind | None = None) -> list[Alert]:
        alerts = db.get_alerts()
        if min_severity is not None:
            alerts = [a for a in alerts if SEVERITY_RANK[a.severity] >= SEVERITY_RANK[min_severity]]
        if kind is not None:
            alerts = [a for a in alerts if a.kind == kind]
        return alerts

    @app.get("/api/quakes", response_model=list[Quake])
    def list_quakes() -> list[Quake]:
        return db.get_quakes()

    @app.get("/api/precip", response_model=PrecipGrid)
    def precip(response: Response) -> PrecipGrid:
        """Precipitación prevista por el modelo de Open-Meteo sobre una grilla de Chile, hora a hora."""
        grid = load_precip(db)
        if grid is None:
            raise HTTPException(
                status_code=503,
                detail="La precipitación prevista aún no está disponible. Intenta de nuevo en unos minutos.",
            )
        response.headers["Cache-Control"] = "public, max-age=300"
        return grid

    @app.get("/api/forecast/{location_id}", response_model=ForecastResponse)
    def forecast(location_id: str) -> ForecastResponse:
        loc = LOCATIONS_BY_ID.get(location_id)
        if loc is None:
            raise HTTPException(status_code=404, detail="Ubicación no encontrada")
        snap = db.get_snapshot(location_id)
        if snap is None:
            raise HTTPException(status_code=503, detail="Aún no hay datos para esta ubicación")
        return ForecastResponse(
            location=loc,
            fetched_at=snap.fetched_at,
            current=snap.current,
            hourly=snap.hourly,
            alerts=[a for a in db.get_alerts() if a.location_id == location_id],
        )

    @app.post("/api/refresh")
    async def refresh(x_refresh_token: str | None = Header(default=None)) -> dict:
        """Fuerza una ingesta. Pensado para un cron externo (también despierta servicios dormidos)."""
        if settings.refresh_token is None:
            raise HTTPException(status_code=403, detail="Refresh deshabilitado: define REFRESH_TOKEN")
        if not secrets.compare_digest(x_refresh_token or "", settings.refresh_token):
            raise HTTPException(status_code=401, detail="Token inválido")

        last = db.get_meta("last_attempt_at")
        if last:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
            if age < settings.refresh_min_interval_s:
                return {"status": "skipped", "age_seconds": int(age)}

        result = await ingest_once()
        return {"status": "ok" if result.ok else "partial", **asdict(result)}

    return app