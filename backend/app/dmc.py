"""Observaciones de estaciones de la Dirección Meteorológica de Chile (DMC).

La DMC ofrece servicios web JSON oficiales y gratuitos, pero exigen registrarse en
https://climatologia.meteochile.gob.cl/application/usuario/registroUsuario y enviar el correo
(`usuario`) y el `token` personal en cada petición. Sin credenciales, esta fuente se desactiva sola.

Se usa el servicio GeoJSON `getRiesgoIncendio` porque entrega, en una respuesta pequeña (una
entidad por estación), las condiciones actuales y el viento máximo de las últimas 6 horas. Los
servicios de datos por minuto pesan decenas de MB y no caben en una función serverless.

Unidades según la documentación de la DMC: temperatura en °C, humedad en %, viento actual en
**nudos** y viento máximo de 6 h en **km/h**. Los valores pueden llegar como número o como texto con
unidad ("20.2 °C"), y faltantes como null, por lo que el análisis es tolerante.

NOTA: esta integración se escribió contra la documentación, no contra respuestas reales (requiere
credenciales). Verifícala con `python -m scripts.live_check` después de registrarte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

import httpx

from .clients import UpstreamError, get_json
from .models import Location, Observation
from .rules import haversine_km

DMC_FIRE_URL = "https://climatologia.meteochile.gob.cl/application/geoservicios/getRiesgoIncendio"
KNOT_TO_KMH = 1.852
MAX_STATION_DISTANCE_KM = 60.0

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Station:
    code: str | None
    name: str
    lat: float
    lon: float
    temperature_c: float | None
    humidity_pct: float | None
    wind_kmh: float | None
    wind_max_6h_kmh: float | None
    temp_max_today_c: float | None
    temp_max_tomorrow_c: float | None


def parse_number(value: Any) -> float | None:
    """Acepta 12, 12.5, "12.5", "20.2 °C", "65 %", "12,3 kt" y null."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.search(str(value))
    return float(match.group().replace(",", ".")) if match else None


def _round(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def parse_stations(data: Any) -> list[Station]:
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise UpstreamError("DMC: formato inesperado (se esperaba un GeoJSON FeatureCollection)")

    stations: list[Station] = []
    for feature in data["features"]:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = parse_number(coords[0]), parse_number(coords[1])
        name = str(props.get("nombreEstacion") or "").strip()
        if lon is None or lat is None or not name:
            continue
        wind_kt = parse_number(props.get("intensidadDelViento"))
        code = props.get("codigoNacional")
        stations.append(
            Station(
                code=str(code) if code is not None else None,
                name=name,
                lat=lat,
                lon=lon,
                temperature_c=parse_number(props.get("temperatura")),
                humidity_pct=parse_number(props.get("humedad")),
                wind_kmh=_round(wind_kt * KNOT_TO_KMH) if wind_kt is not None else None,
                wind_max_6h_kmh=parse_number(props.get("intensidadVientoMaximo6h")),
                temp_max_today_c=parse_number(props.get("temperaturaMaximaHoy")),
                temp_max_tomorrow_c=parse_number(props.get("temperaturaMaximaManana")),
            )
        )
    return stations


async def fetch_dmc(client: httpx.AsyncClient, user: str, token: str) -> list[Station]:
    data = await get_json(client, DMC_FIRE_URL, {"usuario": user, "token": token}, label="DMC")
    return parse_stations(data)


def nearest_observation(
    loc: Location, stations: Sequence[Station], max_km: float = MAX_STATION_DISTANCE_KM
) -> Observation | None:
    """Estación más cercana a la ciudad (dentro de `max_km`) que tenga al menos un dato útil."""
    best: tuple[float, Station] | None = None
    for st in stations:
        if st.temperature_c is None and st.humidity_pct is None and st.wind_kmh is None:
            continue
        d = haversine_km(loc.lat, loc.lon, st.lat, st.lon)
        if d <= max_km and (best is None or d < best[0]):
            best = (d, st)
    if best is None:
        return None
    distance, st = best
    return Observation(
        station=st.name,
        station_code=st.code,
        distance_km=round(distance, 1),
        temperature_c=st.temperature_c,
        humidity_pct=st.humidity_pct,
        wind_kmh=st.wind_kmh,
        wind_max_6h_kmh=st.wind_max_6h_kmh,
        temp_max_today_c=st.temp_max_today_c,
        temp_max_tomorrow_c=st.temp_max_tomorrow_c,
    )
