"""Datos sintéticos para grabar demos (GIF, capturas) cuando el clima real está tranquilo.

Activa con DEMO_MODE=true. Pasan por el mismo motor de reglas que los datos reales; solo cambia el
origen. La interfaz muestra un aviso permanente mientras este modo esté activo.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from .clients import PRECIP_HOURS
from .grid import GRID_POINTS, GRID_STEP_DEG
from .locations import LOCATIONS
from .models import Current, Hourly, Location, PrecipCell, PrecipGrid, Quake, Snapshot, SourceStatus
from .service import SOURCE_NAMES, SOURCE_ORDER, assemble_snapshot

CHILE_TZ = timezone(timedelta(hours=-3))  # aproximación suficiente para una demo

# Escenarios: {ciudad: {serie: {horas_desde_ahora: valor}}}
SCENARIOS: dict[str, dict[str, dict[int, float]]] = {
    "punta-arenas": {"gust_kmh": {4: 88, 5: 96, 6: 91}, "weather_code": {9: 73, 10: 75, 11: 73}},
    "puerto-montt": {"precipitation_mm": {5: 6, 6: 14, 7: 11}, "gust_kmh": {7: 78, 8: 74}, "weather_code": {6: 65, 7: 65}},
    "concepcion": {"weather_code": {9: 96, 10: 96}, "precipitation_mm": {9: 9, 10: 7}},
    "temuco": {"temperature_c": {14: -4.2, 15: -4.8}, "humidity_pct": {14: 85, 15: 88}},
    "calama": {"temperature_c": {13: -1.5}, "humidity_pct": {13: 75}},
    "copiapo": {"temperature_c": {3: 38.2, 4: 38.6, 5: 37.9}},
    "valparaiso": {"gust_kmh": {7: 63, 8: 66}},
}


def build_hourly(loc: Location, now_local: datetime, overrides: dict[str, dict[int, float]]) -> Hourly:
    start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    now_i = now_local.hour
    base_temp = 26 + (loc.lat + 18) * 0.45  # más frío hacia el sur

    series: dict[str, list] = {k: [] for k in (
        "time", "temperature_c", "humidity_pct", "precipitation_mm", "wind_kmh", "gust_kmh", "weather_code")}
    for h in range(72):
        t = start + timedelta(hours=h)
        daily = 5 * math.sin((t.hour - 9) / 24 * 2 * math.pi)  # máximo hacia las 15h
        wind = 12 + 4 * math.sin(h / 5)
        series["time"].append(t.strftime("%Y-%m-%dT%H:00"))
        series["temperature_c"].append(round(base_temp + daily, 1))
        series["humidity_pct"].append(round(min(95, max(25, 62 - 3 * daily)), 0))
        series["precipitation_mm"].append(0.0)
        series["wind_kmh"].append(round(wind, 1))
        series["gust_kmh"].append(round(wind * 1.7, 1))
        series["weather_code"].append(2)

    for key, offsets in overrides.items():
        for offset, value in offsets.items():
            index = now_i + offset
            if 0 <= index < 72:
                series[key][index] = value
    return Hourly(**series)


def build_demo_snapshot(*, now: datetime, cache_ttl_s: int) -> Snapshot:
    now_local = now.astimezone(CHILE_TZ)
    i = now_local.hour
    forecasts: dict[str, tuple[Current, Hourly]] = {}
    for loc in LOCATIONS:
        hourly = build_hourly(loc, now_local, SCENARIOS.get(loc.id, {}))
        current = Current(
            time=now_local.strftime("%Y-%m-%dT%H:%M"),
            temperature_c=hourly.temperature_c[i],
            humidity_pct=hourly.humidity_pct[i],
            precipitation_mm=hourly.precipitation_mm[i],
            wind_kmh=hourly.wind_kmh[i],
            gust_kmh=hourly.gust_kmh[i],
            weather_code=hourly.weather_code[i],
        )
        # Igual que la lectura real: 6 h hacia atrás y 48 hacia adelante.
        lo, hi = max(0, i - 6), i + 48
        forecasts[loc.id] = (current, Hourly(**{k: v[lo:hi] for k, v in hourly.model_dump().items()}))

    def hours_ago(h: float) -> int:
        return int((now - timedelta(hours=h)).timestamp() * 1000)

    quakes = [
        Quake(id="demo-1", magnitude=6.4, place="42 km al O de Valparaíso", time_ms=hours_ago(3),
              lat=-33.2, lon=-72.1, depth_km=28.0, source="csn", usgs_magnitude=6.2),
        Quake(id="demo-2", magnitude=5.3, place="62 km al SO de Iquique", time_ms=hours_ago(20),
              lat=-20.6, lon=-70.5, depth_km=45.0, source="csn", usgs_magnitude=5.1),
        Quake(id="demo-3", magnitude=4.7, place="Aysén, Chile", time_ms=hours_ago(40), lat=-45.9, lon=-73.1, depth_km=15.0),
        Quake(id="demo-4", magnitude=4.9, place="Offshore Maule, Chile", time_ms=hours_ago(70), lat=-35.9, lon=-73.4, depth_km=22.0),
        Quake(id="demo-5", magnitude=5.1, place="Antofagasta, Chile", time_ms=hours_ago(110), lat=-23.9, lon=-70.2, depth_km=60.0),
        Quake(id="demo-6", magnitude=4.6, place="Los Lagos, Chile", time_ms=hours_ago(150), lat=-41.9, lon=-73.6, depth_km=18.0),
    ]

    sources = [
        SourceStatus(id=sid, name=SOURCE_NAMES[sid], enabled=sid != "dmc", ok=sid != "dmc",
                     detail="Datos de demostración" if sid != "dmc" else "No se usa en la demo")
        for sid in SOURCE_ORDER
    ]
    return assemble_snapshot(now=now, forecasts=forecasts, quakes=quakes, stations=[], sources=sources,
                             cache_ttl_s=cache_ttl_s, demo=True)


def build_demo_precip(*, now: datetime) -> PrecipGrid:
    """Sistema frontal sintético que sube desde Aysén más una tormenta aislada cerca de Concepción.

    Es una función pura de `now` (sin azar): mismas entradas, misma grilla. Se marca `demo=True`.
    """
    start = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    times = [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00") for h in range(PRECIP_HOURS)]

    cells: list[PrecipCell] = []
    for lat, lon in GRID_POINTS:
        mm: list[float | None] = []
        for h in range(PRECIP_HOURS):
            # Banda frontal: avanza ~0,55° de latitud por hora y llueve más hacia el lado oeste (la costa).
            band = math.exp(-((lat - (-46.0 + 0.55 * h)) ** 2) / (2 * 2.4**2))
            windward = 0.55 + 0.45 * math.exp(-((lon + 73.5) ** 2) / (2 * 2.0**2))
            intensity = 7.5 * (0.75 + 0.25 * math.sin(h / 3)) * band * windward
            # Textura determinista para que no parezca una mancha perfecta.
            intensity *= 0.8 + 0.2 * math.sin(lat * 3.1 + lon * 2.3 + h * 0.7)
            # Tormenta aislada sobre el Biobío, entre +8 y +11 horas.
            storm = 9.0 * math.exp(-((lat + 36.8) ** 2 + (lon + 73.0) ** 2) / (2 * 1.0**2)) * math.exp(
                -((h - 9.5) ** 2) / (2 * 1.5**2)
            )
            total = intensity + storm
            mm.append(round(total, 1) if total >= 0.05 else 0.0)
        cells.append(PrecipCell(lat=lat, lon=lon, mm=mm))

    return PrecipGrid(
        fetched_at=now.isoformat(timespec="seconds"),
        step_deg=GRID_STEP_DEG,
        times=times,
        cells=cells,
        demo=True,
    )
