"""Clientes HTTP para las APIs gratuitas: Open-Meteo (clima) y USGS (sismos)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

import httpx

from .models import Current, Hourly, Location, Quake

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
