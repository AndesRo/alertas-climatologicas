"""Modelos de datos compartidos por el motor de reglas, la base de datos y la API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Severity = Literal["yellow", "orange", "red"]
SeverityOrNone = Literal["none", "yellow", "orange", "red"]
AlertKind = Literal["wind", "rain", "storm", "frost", "heat", "snow", "earthquake"]

SEVERITY_RANK: dict[str, int] = {"none": 0, "yellow": 1, "orange": 2, "red": 3}


class Location(BaseModel):
    id: str
    name: str
    region: str
    lat: float
    lon: float


class Current(BaseModel):
    """Condiciones actuales. `time` está en hora local de la ubicación."""

    time: str
    temperature_c: float | None = None
    humidity_pct: float | None = None
    precipitation_mm: float | None = None
    wind_kmh: float | None = None
    gust_kmh: float | None = None
    weather_code: int | None = None


class Hourly(BaseModel):
    """Serie horaria. Todas las listas tienen el mismo largo que `time`."""

    time: list[str]
    temperature_c: list[float | None]
    humidity_pct: list[float | None]
    precipitation_mm: list[float | None]
    wind_kmh: list[float | None]
    gust_kmh: list[float | None]
    weather_code: list[int | None]


class Quake(BaseModel):
    id: str
    magnitude: float
    place: str
    time_ms: int
    lat: float
    lon: float
    depth_km: float | None = None
    url: str | None = None


class Alert(BaseModel):
    key: str
    kind: AlertKind
    severity: Severity
    title: str
    message: str
    location_id: str | None = None
    location_name: str | None = None
    lat: float
    lon: float
    value: float
    unit: str
    at: str | None = None


class LocationSummary(Location):
    current: Current | None = None
    severity: SeverityOrNone = "none"
    alert_count: int = 0


class ForecastResponse(BaseModel):
    location: Location
    fetched_at: str
    current: Current
    hourly: Hourly
    alerts: list[Alert]


class PrecipCell(BaseModel):
    """Una celda de la grilla: `mm[i]` es la precipitación (mm) de la hora que termina en `times[i]`."""

    lat: float
    lon: float
    mm: list[float | None]


class PrecipGrid(BaseModel):
    """Precipitación prevista por el modelo de Open-Meteo sobre una grilla de Chile.

    Es una predicción numérica, no una medición. `times` está en UTC (sin sufijo Z) y es
    igual para todas las celdas. La celda `i` cubre `step_deg` grados centrados en (lat, lon).
    """

    fetched_at: str
    step_deg: float
    times: list[str]
    cells: list[PrecipCell]
    demo: bool = False


class StatusResponse(BaseModel):
    last_ingest_at: str | None
    last_error: str | None
    locations: int
    alerts: int
    quakes: int
    interval_min: int