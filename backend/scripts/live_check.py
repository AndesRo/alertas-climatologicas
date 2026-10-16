"""Prueba de humo contra las APIs reales (Open-Meteo y USGS), con una base temporal.

Úsalo una vez después de clonar, o cuando algo falle en producción:
    python -m scripts.live_check
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from app.config import get_settings
from app.db import Database
from app.ingest import run_ingest


def main() -> None:
    settings = get_settings()
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "live-check.db")
        db.init()
        result = asyncio.run(run_ingest(db, settings))

        print(f"Pronósticos: {result.forecasts} | Sismos (7 días, M4.5+): {result.quakes} | Alertas: {result.alerts}")
        for alert in db.get_alerts():
            print(f"  [{alert.severity:6}] {alert.title} - {alert.message}")
        if result.errors:
            print("Errores:")
            for error in result.errors:
                print(f"  - {error}")
            raise SystemExit(1)
        print("OK: ambas fuentes respondieron.")


if __name__ == "__main__":
    main()
