"""Datos sintéticos para los tests: ninguna prueba toca la red."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Hourly

START = datetime(2026, 10, 15, 0, 0)
CURRENT_TIME = "2026-10-15T10:15"  # equivale al índice 10 de la serie
NOW = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)

_DEFAULTS: dict[str, float | int] = {
    "temperature_c": 15.0,
    "humidity_pct": 50.0,
    "precipitation_mm": 0.0,
    "wind_kmh": 10.0,
    "gust_kmh": 20.0,
    "weather_code": 1,
}


def make_hourly(hours: int = 72, **overrides: dict[int, float | int]) -> Hourly:
    """Serie horaria tranquila; `overrides` pisa valores por índice: make_hourly(gust_kmh={14: 82})."""
    times = [(START + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00") for h in range(hours)]
    data: dict[str, list] = {"time": times}
    for key, default in _DEFAULTS.items():
        values: list = [default] * hours
        for index, value in overrides.get(key, {}).items():
            values[index] = value
        data[key] = values
    return Hourly(**data)


def open_meteo_item(**overrides: dict[int, float | int]) -> dict:
    """Un elemento con el mismo formato que devuelve Open-Meteo."""
    h = make_hourly(**overrides)
    return {
        "current": {
            "time": CURRENT_TIME,
            "temperature_2m": 14.2,
            "relative_humidity_2m": 55,
            "precipitation": 0.0,
            "weather_code": 2,
            "wind_speed_10m": 12.0,
            "wind_gusts_10m": 25.0,
        },
        "hourly": {
            "time": h.time,
            "temperature_2m": h.temperature_c,
            "relative_humidity_2m": h.humidity_pct,
            "precipitation": h.precipitation_mm,
            "weather_code": h.weather_code,
            "wind_speed_10m": h.wind_kmh,
            "wind_gusts_10m": h.gust_kmh,
        },
    }


def usgs_sample() -> dict:
    """Un sismo M6.2 reciente frente a Valparaíso y uno M4.8 sin relevancia."""
    return {
        "features": [
            {
                "id": "us7000test1",
                "properties": {
                    "mag": 6.2,
                    "place": "45 km W of Valparaíso, Chile",
                    "time": NOW_MS - 3_600_000,
                    "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test1",
                },
                "geometry": {"coordinates": [-71.9, -33.1, 35.0]},
            },
            {
                "id": "us7000test2",
                "properties": {"mag": 4.8, "place": "Offshore Atacama, Chile", "time": NOW_MS - 7_200_000},
                "geometry": {"coordinates": [-71.0, -28.0, 20.0]},
            },
        ]
    }
