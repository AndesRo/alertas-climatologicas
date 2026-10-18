"""Reúne las fuentes, aplica el motor de reglas y entrega un `Snapshot` listo para la interfaz.

Sin base de datos: en Vercel no hay disco persistente ni procesos en segundo plano. El resultado se
guarda en memoria (mientras la instancia siga viva) y, sobre todo, lo cachea el CDN de Vercel con
las cabeceras `Cache-Control` que añade la API. Cada fuente falla por separado.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Sequence

from .clients import UpstreamError, fetch_forecasts, fetch_precip_grid, fetch_quakes, make_client
from .config import Settings
from .csn import fetch_csn, merge_csn
from .dmc import Station, fetch_dmc, nearest_observation
from .grid import GRID_POINTS
from .locations import LOCATIONS
from .models import (
    Alert,
    Current,
    ForecastBlock,
    Hourly,
    LocationSummary,
    PrecipGrid,
    Quake,
    Snapshot,
    SourceStatus,
)
from .rules import evaluate_location, evaluate_quakes, max_severity, sort_alerts

logger = logging.getLogger("centinela.service")

SOURCE_NAMES = {
    "open_meteo": "Open-Meteo",
    "usgs": "USGS",
    "csn": "CSN (vía Gael Cloud)",
    "dmc": "DMC",
}
SOURCE_ORDER = ("open_meteo", "usgs", "csn", "dmc")
# Si todas las fuentes fallan, se reintenta pronto en lugar de esperar un ciclo completo.
RETRY_AFTER_FAILURE_S = 60
# Si una fuente falla se muestra su última lectura buena, pero solo hasta este límite: un pronóstico de
# hace días no describe el presente y sus alertas serían falsas. Pasado el límite se prefiere un error.
MAX_STALE_S = 6 * 3600


class NoDataError(RuntimeError):
    """Ninguna fuente respondió y no hay datos anteriores que mostrar."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _age_s(moment: datetime | None, now: datetime) -> float:
    return float("inf") if moment is None else (now - moment).total_seconds()


def _is_fresh(checked_at: datetime | None, window_s: float, now: datetime) -> bool:
    """¿Sigue vigente la caché? Se mide con el reloj de pared a propósito.

    El reloj monotónico no avanza mientras un portátil está suspendido ni mientras una función
    serverless está congelada entre peticiones: una lectura de hace dos días parecería vigente y la
    interfaz mostraría datos viejos (y ocultaría la capa de lluvia, que descarta grillas vencidas).
    Si el reloj de pared retrocede tampoco se confía en la caché.
    """
    return 0 <= _age_s(checked_at, now) < window_s


def assemble_snapshot(
    *,
    now: datetime,
    forecasts: dict[str, tuple[Current, Hourly]] | None,
    quakes: Sequence[Quake],
    stations: Sequence[Station],
    sources: list[SourceStatus],
    cache_ttl_s: int,
    demo: bool = False,
) -> Snapshot:
    """Función pura: mismos datos de entrada, mismo resultado. No hace red ni lee el reloj."""
    forecasts = forecasts or {}

    alerts: list[Alert] = []
    for loc in LOCATIONS:
        item = forecasts.get(loc.id)
        if item is not None:
            current, hourly = item
            alerts.extend(evaluate_location(loc, current.time, hourly))
    alerts.extend(evaluate_quakes(quakes, LOCATIONS, now_ms=int(now.timestamp() * 1000)))
    alerts = sort_alerts(alerts)

    by_location: dict[str, list[Alert]] = {}
    for alert in alerts:
        if alert.location_id:
            by_location.setdefault(alert.location_id, []).append(alert)

    locations = []
    for loc in LOCATIONS:
        item = forecasts.get(loc.id)
        own = by_location.get(loc.id, [])
        locations.append(
            LocationSummary(
                **loc.model_dump(),
                current=item[0] if item else None,
                observation=nearest_observation(loc, stations),
                severity=max_severity(own),
                alert_count=len(own),
            )
        )

    return Snapshot(
        generated_at=now.isoformat(timespec="seconds"),
        demo=demo,
        cache_ttl_s=cache_ttl_s,
        sources=sources,
        locations=locations,
        alerts=alerts,
        quakes=list(quakes),
        forecasts={loc_id: ForecastBlock(current=c, hourly=h) for loc_id, (c, h) in forecasts.items()},
    )


@dataclass
class _Fetched:
    ok: bool
    value: Any = None
    error: str | None = None


async def _guard(coro: Awaitable[Any]) -> _Fetched:
    try:
        return _Fetched(ok=True, value=await coro)
    except UpstreamError as exc:
        logger.warning("Fuente no disponible: %s", exc)
        return _Fetched(ok=False, error=str(exc))
    except Exception:  # noqa: BLE001 - una fuente con un bug no debe tumbar a las demás
        logger.exception("Error inesperado al consultar una fuente")
        return _Fetched(ok=False, error="error inesperado")


class SnapshotService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self._snapshot: Snapshot | None = None
        # Cuándo se obtuvo de las fuentes, y desde cuándo y por cuántos segundos vale como vigente.
        self._built_at: datetime | None = None
        self._checked_at: datetime | None = None
        self._window_s = 0.0
        # Última lectura buena de cada fuente y cuándo se obtuvo (ver MAX_STALE_S).
        self._last_good: dict[str, tuple[Any, datetime]] = {}
        # La grilla de precipitación tiene su propia caché y su propio candado: son ~200 puntos que
        # Open-Meteo cuenta uno a uno, así que se renueva menos seguido y sin arrastrar al resto.
        self._precip_lock = asyncio.Lock()
        self._precip: PrecipGrid | None = None
        self._precip_built_at: datetime | None = None
        self._precip_checked_at: datetime | None = None
        self._precip_window_s = 0.0

    async def get_precip(self) -> PrecipGrid:
        """Grilla de precipitación prevista.

        Lanza `NoDataError` si nunca se pudo obtener o si la última lectura buena tiene más de `MAX_STALE_S`.
        """
        if self._precip is not None and _is_fresh(self._precip_checked_at, self._precip_window_s, _now()):
            return self._precip
        async with self._precip_lock:
            if self._precip is not None and _is_fresh(self._precip_checked_at, self._precip_window_s, _now()):
                return self._precip
            try:
                self._precip = await self._build_precip()
                self._precip_built_at = self._precip_checked_at = _now()
                self._precip_window_s = self._settings.precip_ttl_s
            except NoDataError:
                if self._precip is None or _age_s(self._precip_built_at, _now()) > MAX_STALE_S:
                    self._precip = None  # una previsión de hace horas no se muestra como si fuera actual
                    raise
                # Mejor la grilla anterior que ninguna; se reintenta pronto.
                self._precip_checked_at = _now()
                self._precip_window_s = RETRY_AFTER_FAILURE_S
            return self._precip

    async def _build_precip(self) -> PrecipGrid:
        settings = self._settings
        now = datetime.now(timezone.utc)

        if settings.demo_mode:
            from .demo import build_demo_precip

            return build_demo_precip(now=now)

        try:
            async with make_client(settings.user_agent) as client:
                return await asyncio.wait_for(
                    fetch_precip_grid(client, GRID_POINTS, now=now), timeout=settings.build_timeout_s
                )
        except UpstreamError as exc:
            logger.warning("Grilla de precipitación no disponible: %s", exc)
            raise NoDataError(str(exc)) from None
        except asyncio.TimeoutError:
            logger.warning("Grilla de precipitación: tiempo de espera agotado")
            raise NoDataError("tiempo de espera agotado") from None

    async def get(self) -> Snapshot:
        if self._snapshot is not None and _is_fresh(self._checked_at, self._window_s, _now()):
            return self._snapshot
        async with self._lock:
            # Otra petición pudo reconstruirlo mientras esperábamos el candado.
            if self._snapshot is not None and _is_fresh(self._checked_at, self._window_s, _now()):
                return self._snapshot
            try:
                self._snapshot = await self._build()
                self._built_at = self._checked_at = _now()
                self._window_s = self._settings.cache_ttl_s
            except NoDataError:
                if self._snapshot is None or _age_s(self._built_at, _now()) > MAX_STALE_S:
                    self._snapshot = None
                    raise
                # Mejor datos viejos que ninguno (hasta MAX_STALE_S); se reintenta pronto.
                self._checked_at = _now()
                self._window_s = RETRY_AFTER_FAILURE_S
            return self._snapshot

    async def _build(self) -> Snapshot:
        settings = self._settings
        now = datetime.now(timezone.utc)

        if settings.demo_mode:
            from .demo import build_demo_snapshot

            return build_demo_snapshot(now=now, cache_ttl_s=settings.cache_ttl_s)

        results = await self._fetch_all(now)

        sources: list[SourceStatus] = []
        data: dict[str, Any] = {}
        for sid in SOURCE_ORDER:
            name = SOURCE_NAMES[sid]
            result = results.get(sid)
            if result is None:  # fuente opcional sin configurar (DMC sin credenciales)
                sources.append(SourceStatus(id=sid, name=name, enabled=False, ok=False,
                                            detail="Sin credenciales. Es opcional."))
                continue
            if result.ok:
                self._last_good[sid] = (result.value, now)
                data[sid] = result.value
                sources.append(SourceStatus(id=sid, name=name, count=len(result.value)))
                continue
            kept = self._last_good.get(sid)
            if kept is not None and _age_s(kept[1], now) <= MAX_STALE_S:
                data[sid] = kept[0]
                sources.append(SourceStatus(id=sid, name=name, ok=False, stale=True, detail=result.error,
                                            count=len(kept[0])))
            else:
                # Un dato de hace más de MAX_STALE_S ya no describe el presente: mejor no mostrarlo.
                self._last_good.pop(sid, None)
                data[sid] = None
                sources.append(SourceStatus(id=sid, name=name, ok=False, detail=result.error))

        if data.get("open_meteo") is None and data.get("usgs") is None:
            raise NoDataError("Open-Meteo y USGS no respondieron y no hay datos anteriores.")

        quakes: list[Quake] = list(data.get("usgs") or [])
        events = data.get("csn") or []
        confirmed = 0
        if quakes and events:
            quakes, confirmed = merge_csn(quakes, events)
        for status in sources:
            if status.id == "csn" and status.ok:
                status.detail = f"{confirmed} sismo(s) confirmado(s) con USGS"

        return assemble_snapshot(
            now=now,
            forecasts=data.get("open_meteo"),
            quakes=quakes,
            stations=data.get("dmc") or [],
            sources=sources,
            cache_ttl_s=settings.cache_ttl_s,
        )

    async def _fetch_all(self, now: datetime) -> dict[str, _Fetched]:
        settings = self._settings
        async with make_client(settings.user_agent) as client:
            jobs: dict[str, Awaitable[Any]] = {
                "open_meteo": fetch_forecasts(client, LOCATIONS),
                "usgs": fetch_quakes(client, now=now),
                "csn": fetch_csn(client),
            }
            if settings.dmc_enabled:
                jobs["dmc"] = fetch_dmc(client, settings.dmc_user or "", settings.dmc_token or "")

            tasks = {sid: asyncio.create_task(_guard(coro)) for sid, coro in jobs.items()}
            _, pending = await asyncio.wait(tasks.values(), timeout=settings.build_timeout_s)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

            return {
                sid: task.result() if task not in pending else _Fetched(ok=False, error="tiempo de espera agotado")
                for sid, task in tasks.items()
            }
