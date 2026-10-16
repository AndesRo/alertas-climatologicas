"""Motor de reglas: convierte pronósticos y sismos en alertas con severidad.

Es la parte "propia" del proyecto (ninguna API gratuita entrega alertas oficiales
para Chile), por eso es código puro, sin red ni base de datos, y está cubierto por tests.

Todas las funciones trabajan con hora local de cada ubicación (Open-Meteo con
``timezone=auto``), por lo que las horas se comparan como texto ISO sin convertir zonas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from .models import (
    SEVERITY_RANK,
    Alert,
    AlertKind,
    Hourly,
    Location,
    Quake,
    Severity,
    SeverityOrNone,
)


@dataclass(frozen=True)
class Threshold:
    yellow: float
    orange: float
    red: float


# Umbrales (informativos; no reemplazan a los organismos oficiales).
GUST_KMH = Threshold(60, 75, 90)
RAIN_MM_H = Threshold(5, 10, 20)
HEAT_C = Threshold(35, 38, 40)
FROST_C = Threshold(0, -3, -6)  # descendente: mientras más bajo, peor
FROST_MIN_HUMIDITY = 60  # solo exigido para el nivel amarillo
QUAKE_MAG = Threshold(5.0, 6.0, 7.0)
QUAKE_RADIUS_KM = 300.0
QUAKE_MAX_AGE_HOURS = 48
HORIZON_HOURS = 24

# Códigos WMO (https://open-meteo.com/en/docs): 95 tormenta, 96/99 con granizo.
STORM_CODES: dict[int, Severity] = {95: "yellow", 96: "orange", 99: "red"}
# 73 nieve moderada, 75 nieve fuerte, 86 chubascos de nieve intensos.
SNOW_CODES: dict[int, Severity] = {73: "yellow", 75: "orange", 86: "orange"}


def describe_rules() -> dict:
    """Expone los umbrales vigentes para que el frontend no los duplique."""

    def as_dict(t: Threshold) -> dict[str, float]:
        return {"yellow": t.yellow, "orange": t.orange, "red": t.red}

    return {
        "wind_gust_kmh": as_dict(GUST_KMH),
        "rain_mm_h": as_dict(RAIN_MM_H),
        "heat_c": as_dict(HEAT_C),
        "frost_c": as_dict(FROST_C),
        "quake_magnitude": as_dict(QUAKE_MAG),
        "quake_radius_km": QUAKE_RADIUS_KM,
        "horizon_hours": HORIZON_HOURS,
    }


def classify(value: float, th: Threshold, *, lower_is_worse: bool = False) -> Severity | None:
    """Devuelve la severidad que corresponde a `value`, o None si no alcanza ningún umbral."""
    if lower_is_worse:
        if value <= th.red:
            return "red"
        if value <= th.orange:
            return "orange"
        if value <= th.yellow:
            return "yellow"
        return None
    if value >= th.red:
        return "red"
    if value >= th.orange:
        return "orange"
    if value >= th.yellow:
        return "yellow"
    return None


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def forecast_window(hourly: Hourly, current_time: str, horizon_hours: int = HORIZON_HOURS) -> list[int]:
    """Índices de las próximas `horizon_hours` horas, incluyendo la hora en curso."""
    start = current_time[:13] + ":00"
    indexes = [i for i, t in enumerate(hourly.time) if t >= start]
    return indexes[:horizon_hours]


def _when(peak_time: str, reference_time: str) -> str:
    day = "hoy" if peak_time[:10] == reference_time[:10] else "mañana"
    return f"{day} a las {peak_time[11:16]}"


def _peak(values: Sequence[float | None], indexes: Sequence[int]) -> tuple[int | None, float | None]:
    best_i: int | None = None
    best_v: float | None = None
    for i in indexes:
        v = values[i]
        if v is not None and (best_v is None or v > best_v):
            best_i, best_v = i, v
    return best_i, best_v


def _peak_by_code(
    codes: Sequence[int | None], indexes: Sequence[int], mapping: dict[int, Severity]
) -> tuple[int | None, Severity | None, int | None]:
    best: tuple[int, Severity, int] | None = None
    for i in indexes:
        code = codes[i]
        sev = mapping.get(code) if code is not None else None
        if sev is not None and (best is None or SEVERITY_RANK[sev] > SEVERITY_RANK[best[1]]):
            best = (i, sev, code)  # type: ignore[assignment]
    if best is None:
        return None, None, None
    return best


def _frost_severity(temp: float, humidity: float | None) -> Severity | None:
    sev = classify(temp, FROST_C, lower_is_worse=True)
    if sev == "yellow" and humidity is not None and humidity < FROST_MIN_HUMIDITY:
        return None
    return sev


def sort_alerts(alerts: list[Alert]) -> list[Alert]:
    return sorted(alerts, key=lambda a: (-SEVERITY_RANK[a.severity], a.kind, a.location_name or ""))


def max_severity(alerts: Sequence[Alert]) -> SeverityOrNone:
    best: SeverityOrNone = "none"
    for a in alerts:
        if SEVERITY_RANK[a.severity] > SEVERITY_RANK[best]:
            best = a.severity
    return best


def evaluate_location(
    loc: Location,
    current_time: str,
    hourly: Hourly,
    horizon_hours: int = HORIZON_HOURS,
) -> list[Alert]:
    """Evalúa las próximas horas de una ubicación y devuelve a lo más una alerta por tipo."""
    idx = forecast_window(hourly, current_time, horizon_hours)
    if not idx:
        return []

    alerts: list[Alert] = []

    def add(kind: AlertKind, severity: Severity, title: str, message: str, i: int, value: float, unit: str) -> None:
        alerts.append(
            Alert(
                key=f"{kind}:{loc.id}",
                kind=kind,
                severity=severity,
                title=title,
                message=message,
                location_id=loc.id,
                location_name=loc.name,
                lat=loc.lat,
                lon=loc.lon,
                value=round(value, 1),
                unit=unit,
                at=hourly.time[i],
            )
        )

    # Viento: ráfagas
    i, v = _peak(hourly.gust_kmh, idx)
    if i is not None and v is not None and (sev := classify(v, GUST_KMH)):
        add(
            "wind", sev, "Ráfagas fuertes",
            f"Ráfagas de hasta {v:.0f} km/h previstas {_when(hourly.time[i], current_time)} en {loc.name}.",
            i, v, "km/h",
        )

    # Lluvia: intensidad horaria
    i, v = _peak(hourly.precipitation_mm, idx)
    if i is not None and v is not None and (sev := classify(v, RAIN_MM_H)):
        add(
            "rain", sev, "Lluvia intensa",
            f"Precipitación de hasta {v:.1f} mm/h prevista {_when(hourly.time[i], current_time)} en {loc.name}.",
            i, v, "mm/h",
        )

    # Tormenta eléctrica
    i, sev, code = _peak_by_code(hourly.weather_code, idx, STORM_CODES)
    if i is not None and sev is not None and code is not None:
        hail = " con granizo" if code in (96, 99) else ""
        add(
            "storm", sev, "Tormenta eléctrica",
            f"Tormenta eléctrica{hail} prevista {_when(hourly.time[i], current_time)} en {loc.name}.",
            i, float(code), "WMO",
        )

    # Helada: temperatura mínima (el nivel amarillo exige humedad alta)
    frost: tuple[int, Severity, float] | None = None
    for i in idx:
        t = hourly.temperature_c[i]
        if t is None:
            continue
        s = _frost_severity(t, hourly.humidity_pct[i])
        if s is None:
            continue
        if frost is None or (SEVERITY_RANK[s], -t) > (SEVERITY_RANK[frost[1]], -frost[2]):
            frost = (i, s, t)
    if frost is not None:
        i, sev, t = frost
        add(
            "frost", sev, "Riesgo de helada",
            f"Temperatura de hasta {t:.1f} °C prevista {_when(hourly.time[i], current_time)} en {loc.name}.",
            i, t, "°C",
        )

    # Calor extremo
    i, v = _peak(hourly.temperature_c, idx)
    if i is not None and v is not None and (sev := classify(v, HEAT_C)):
        add(
            "heat", sev, "Calor extremo",
            f"Máxima de {v:.1f} °C prevista {_when(hourly.time[i], current_time)} en {loc.name}.",
            i, v, "°C",
        )

    # Nieve
    i, sev, code = _peak_by_code(hourly.weather_code, idx, SNOW_CODES)
    if i is not None and sev is not None and code is not None:
        add(
            "snow", sev, "Nevadas",
            f"Nevadas {'fuertes ' if sev == 'orange' else ''}previstas {_when(hourly.time[i], current_time)} en {loc.name}.",
            i, float(code), "WMO",
        )

    return sort_alerts(alerts)


def nearest_location(lat: float, lon: float, locations: Sequence[Location]) -> tuple[Location | None, float]:
    best: Location | None = None
    best_d = math.inf
    for loc in locations:
        d = haversine_km(lat, lon, loc.lat, loc.lon)
        if d < best_d:
            best, best_d = loc, d
    return best, best_d


def evaluate_quakes(
    quakes: Sequence[Quake],
    locations: Sequence[Location],
    *,
    now_ms: int,
    max_age_hours: int = QUAKE_MAX_AGE_HOURS,
    radius_km: float = QUAKE_RADIUS_KM,
) -> list[Alert]:
    """Genera una alerta por cada sismo relevante cercano a algún punto monitoreado."""
    alerts: list[Alert] = []
    for q in quakes:
        sev = classify(q.magnitude, QUAKE_MAG)
        if sev is None or now_ms - q.time_ms > max_age_hours * 3_600_000:
            continue
        nearest, dist = nearest_location(q.lat, q.lon, locations)
        if nearest is None or dist > radius_km:
            continue
        when = datetime.fromtimestamp(q.time_ms / 1000, tz=timezone.utc).isoformat(timespec="minutes")
        depth = f", profundidad {q.depth_km:.0f} km" if q.depth_km is not None else ""
        alerts.append(
            Alert(
                key=f"earthquake:{q.id}",
                kind="earthquake",
                severity=sev,
                title=f"Sismo M{q.magnitude:.1f}",
                message=f"Sismo de magnitud {q.magnitude:.1f} a {dist:.0f} km de {nearest.name} ({q.place}){depth}.",
                location_id=nearest.id,
                location_name=nearest.name,
                lat=q.lat,
                lon=q.lon,
                value=q.magnitude,
                unit="M",
                at=when,
            )
        )
    return sort_alerts(alerts)
