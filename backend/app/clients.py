"""Clientes HTTP para las APIs gratuitas: Open-Meteo (clima) y USGS (sismos)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import httpx

from .grid import GRID_STEP_DEG
from .models import Current, Hourly, Location, PrecipCell, PrecipGrid, Quake

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

_VARS = "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,wind_gusts_10m"

# Rectángulo que cubre Chile continental y su plataforma cercana.
CHILE_BBOX = {
    "minlatitude": -56.0,
    "maxlatitude": -17.0,
    "minlongitude": -76.5,
    "maxlongitude": -65.0,
}

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_S = 1.5


class UpstreamError(RuntimeError):
    """Una API externa falló o devolvió algo inesperado."""


async def _get_json(client: httpx.AsyncClient, url: str, params: dict[str, Any]) -> Any:
    last: Exception | None = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            if attempt < RETRY_ATTEMPTS - 1:
                await asyncio.sleep(RETRY_BACKOFF_S * (attempt + 1))
    raise UpstreamError(f"{url}: {last}") from last


def parse_open_meteo(item: dict[str, Any]) -> tuple[Current, Hourly]:
    try:
        cur = item["current"]
        hr = item["hourly"]
        current = Current(
            time=cur["time"],
            temperature_c=cur.get("temperature_2m"),
            humidity_pct=cur.get("relative_humidity_2m"),
            precipitation_mm=cur.get("precipitation"),
            wind_kmh=cur.get("wind_speed_10m"),
            gust_kmh=cur.get("wind_gusts_10m"),
            weather_code=cur.get("weather_code"),
        )
        hourly = Hourly(
            time=hr["time"],
            temperature_c=hr["temperature_2m"],
            humidity_pct=hr["relative_humidity_2m"],
            precipitation_mm=hr["precipitation"],
            wind_kmh=hr["wind_speed_10m"],
            gust_kmh=hr["wind_gusts_10m"],
            weather_code=hr["weather_code"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise UpstreamError(f"Respuesta de Open-Meteo con formato inesperado: {exc}") from exc
    return current, hourly


def trim_hourly(hourly: Hourly, current_time: str, back: int = 6, ahead: int = 48) -> Hourly:
    """Recorta la serie a [hora actual - back, hora actual + ahead) para reducir el peso."""
    start = current_time[:13] + ":00"
    now_i = next((i for i, t in enumerate(hourly.time) if t >= start), len(hourly.time))
    lo, hi = max(0, now_i - back), now_i + ahead
    return Hourly(
        time=hourly.time[lo:hi],
        temperature_c=hourly.temperature_c[lo:hi],
        humidity_pct=hourly.humidity_pct[lo:hi],
        precipitation_mm=hourly.precipitation_mm[lo:hi],
        wind_kmh=hourly.wind_kmh[lo:hi],
        gust_kmh=hourly.gust_kmh[lo:hi],
        weather_code=hourly.weather_code[lo:hi],
    )


async def fetch_forecasts(
    client: httpx.AsyncClient, locations: Sequence[Location]
) -> dict[str, tuple[Current, Hourly]]:
    """Una sola petición para todas las ubicaciones (Open-Meteo admite coordenadas múltiples)."""
    params = {
        "latitude": ",".join(str(loc.lat) for loc in locations),
        "longitude": ",".join(str(loc.lon) for loc in locations),
        "current": _VARS,
        "hourly": _VARS,
        "forecast_days": 3,
        "timezone": "auto",
        "wind_speed_unit": "kmh",
    }
    data = await _get_json(client, OPEN_METEO_URL, params)
    items = data if isinstance(data, list) else [data]
    if len(items) != len(locations):
        raise UpstreamError(f"Open-Meteo devolvió {len(items)} resultados para {len(locations)} ubicaciones")

    result: dict[str, tuple[Current, Hourly]] = {}
    for loc, item in zip(locations, items):
        current, hourly = parse_open_meteo(item)
        result[loc.id] = (current, trim_hourly(hourly, current.time))
    return result


# --- grilla de precipitación prevista -------------------------------------------------------------
PRECIP_HOURS = 25  # la hora en curso más las 24 siguientes
PRECIP_CHUNK = 50  # puntos por petición: mantiene la URL corta y cada llamada liviana
PRECIP_LABEL = "Open-Meteo (grilla)"


def _precip_window(item: Any, start: str, hours: int) -> tuple[list[str], list[float | None]]:
    """Recorta una serie horaria (UTC) a [start, start + hours)."""
    try:
        times = item["hourly"]["time"]
        values = item["hourly"]["precipitation"]
    except (KeyError, TypeError):
        raise UpstreamError(f"{PRECIP_LABEL}: formato inesperado") from None
    if len(times) != len(values):
        raise UpstreamError(f"{PRECIP_LABEL}: series de distinto largo")
    first = next((i for i, t in enumerate(times) if t >= start), None)
    if first is None:
        raise UpstreamError(f"{PRECIP_LABEL}: la respuesta no incluye la hora actual")
    window = slice(first, first + hours)
    try:
        mm = [None if v is None else round(float(v), 1) for v in values[window]]
    except (TypeError, ValueError):
        raise UpstreamError(f"{PRECIP_LABEL}: valores no numéricos") from None
    return times[window], mm


async def _fetch_precip_chunk(client: httpx.AsyncClient, part: Sequence[tuple[float, float]]) -> list[Any]:
    params = {
        "latitude": ",".join(str(lat) for lat, _ in part),
        "longitude": ",".join(str(lon) for _, lon in part),
        "hourly": "precipitation",
        "forecast_days": 2,
        "timezone": "GMT",
    }
    data = await _get_json(client, OPEN_METEO_URL, params)
    items = data if isinstance(data, list) else [data]
    if len(items) != len(part):
        raise UpstreamError(f"{PRECIP_LABEL}: devolvió {len(items)} resultados para {len(part)} puntos")
    return items


async def fetch_precip_grid(
    client: httpx.AsyncClient,
    points: Sequence[tuple[float, float]],
    *,
    now: datetime | None = None,
    hours: int = PRECIP_HOURS,
    chunk: int = PRECIP_CHUNK,
) -> PrecipGrid:
    """Precipitación horaria prevista (mm) para cada punto de la grilla, en UTC.

    Se usa hora UTC y no `timezone=auto` porque Chile continental tiene dos husos según la época
    del año (Magallanes y el resto): en UTC todas las celdas comparten la misma columna de tiempo.
    Los bloques de puntos se piden en paralelo.
    """
    now = now or datetime.now(timezone.utc)
    start = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00")

    parts = [points[i : i + chunk] for i in range(0, len(points), chunk)]
    # `return_exceptions` evita dejar tareas huérfanas si una falla mientras las otras siguen en vuelo.
    results = await asyncio.gather(*(_fetch_precip_chunk(client, part) for part in parts), return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result

    times: list[str] | None = None
    cells: list[PrecipCell] = []
    for part, items in zip(parts, results):
        for (lat, lon), item in zip(part, items):  # type: ignore[arg-type]
            item_times, mm = _precip_window(item, start, hours)
            if times is None:
                times = item_times
            elif item_times != times:
                raise UpstreamError(f"{PRECIP_LABEL}: las celdas no comparten la misma columna de tiempo")
            cells.append(PrecipCell(lat=lat, lon=lon, mm=mm))

    if times is None:
        raise UpstreamError(f"{PRECIP_LABEL}: respuesta vacía")
    return PrecipGrid(
        fetched_at=now.isoformat(timespec="seconds"),
        step_deg=GRID_STEP_DEG,
        times=times,
        cells=cells,
    )


def parse_usgs(data: dict[str, Any]) -> list[Quake]:
    quakes: list[Quake] = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if props.get("mag") is None or props.get("time") is None or len(coords) < 2:
            continue
        quakes.append(
            Quake(
                id=str(feature["id"]),
                magnitude=float(props["mag"]),
                place=props.get("place") or "Ubicación desconocida",
                time_ms=int(props["time"]),
                lat=float(coords[1]),
                lon=float(coords[0]),
                depth_km=float(coords[2]) if len(coords) > 2 and coords[2] is not None else None,
                url=props.get("url"),
            )
        )
    return sorted(quakes, key=lambda q: q.time_ms, reverse=True)


async def fetch_quakes(
    client: httpx.AsyncClient,
    *,
    now: datetime | None = None,
    days: int = 7,
    min_magnitude: float = 4.5,
) -> list[Quake]:
    now = now or datetime.now(timezone.utc)
    params: dict[str, Any] = {
        "format": "geojson",
        "starttime": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S"),
        "minmagnitude": min_magnitude,
        "orderby": "time",
        **CHILE_BBOX,
    }
    data = await _get_json(client, USGS_URL, params)
    if not isinstance(data, dict):
        raise UpstreamError("USGS devolvió un formato inesperado")
    return parse_usgs(data)