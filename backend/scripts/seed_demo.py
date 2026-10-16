"""Carga datos sintéticos para grabar demos sin depender de las APIs ni del clima real.

Útil para el GIF del README y del post: la mayoría de los días no hay alertas reales.
Pasa por el mismo motor de reglas que usa la ingesta, solo cambia el origen de los datos.

Uso (desde backend/):
    python -m scripts.seed_demo
    SCHEDULER_ENABLED=false uvicorn app.main:create_app --factory

Con SCHEDULER_ENABLED=false el servidor no vuelve a consultar las APIs y no pisa los datos de demo.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.db import Database
from app.locations import LOCATIONS
from app.models import Current, Hourly, Location, Quake
from app.rules import evaluate_location, evaluate_quakes, sort_alerts

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

    series: dict[str, list] = {k: [] for k in
                               ("time", "temperature_c", "humidity_pct", "precipitation_mm", "wind_kmh", "gust_kmh", "weather_code")}
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


def main() -> None:
    settings = get_settings()
    db = Database(settings.db_path)
    db.init()

    now = datetime.now(timezone.utc)
    now_local = now.astimezone(CHILE_TZ)
    snapshots = {}
    alerts = []
    for loc in LOCATIONS:
        hourly = build_hourly(loc, now_local, SCENARIOS.get(loc.id, {}))
        i = now_local.hour
        current = Current(
            time=now_local.strftime("%Y-%m-%dT%H:%M"),
            temperature_c=hourly.temperature_c[i],
            humidity_pct=hourly.humidity_pct[i],
            precipitation_mm=hourly.precipitation_mm[i],
            wind_kmh=hourly.wind_kmh[i],
            gust_kmh=hourly.gust_kmh[i],
            weather_code=hourly.weather_code[i],
        )
        # Igual que la ingesta real: se conservan 6 h hacia atrás y 48 hacia adelante.
        lo = max(0, i - 6)
        hi = i + 48
        trimmed = Hourly(**{k: v[lo:hi] for k, v in hourly.model_dump().items()})
        snapshots[loc.id] = (current, trimmed)
        alerts.extend(evaluate_location(loc, current.time, trimmed))

    def hours_ago(h: float) -> int:
        return int((now - timedelta(hours=h)).timestamp() * 1000)

    quakes = [
        Quake(id="demo-1", magnitude=6.4, place="42 km W of Valparaíso, Chile", time_ms=hours_ago(3),
              lat=-33.2, lon=-72.1, depth_km=28.0),
        Quake(id="demo-2", magnitude=5.3, place="62 km SW of Iquique, Chile", time_ms=hours_ago(20),
              lat=-20.6, lon=-70.5, depth_km=45.0),
        Quake(id="demo-3", magnitude=4.7, place="Aysén, Chile", time_ms=hours_ago(40),
              lat=-45.9, lon=-73.1, depth_km=15.0),
        Quake(id="demo-4", magnitude=4.9, place="Offshore Maule, Chile", time_ms=hours_ago(70),
              lat=-35.9, lon=-73.4, depth_km=22.0),
        Quake(id="demo-5", magnitude=5.1, place="Antofagasta, Chile", time_ms=hours_ago(110),
              lat=-23.9, lon=-70.2, depth_km=60.0),
        Quake(id="demo-6", magnitude=4.6, place="Los Lagos, Chile", time_ms=hours_ago(150),
              lat=-41.9, lon=-73.6, depth_km=18.0),
    ]
    alerts.extend(evaluate_quakes(quakes, LOCATIONS, now_ms=int(now.timestamp() * 1000)))

    iso = now.isoformat(timespec="seconds")
    db.save_snapshots(snapshots, iso)
    db.replace_quakes(quakes)
    db.replace_alerts(sort_alerts(alerts))
    db.set_meta("last_attempt_at", iso)
    db.set_meta("last_ingest_at", iso)
    db.set_meta("last_error", "")
    print(f"Datos de demo cargados en {settings.db_path}: {len(alerts)} alertas, {len(quakes)} sismos.")


if __name__ == "__main__":
    main()
