"""Configuración leída desde variables de entorno, con valores por defecto sensatos."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    db_path: Path
    ingest_interval_min: int
    scheduler_enabled: bool
    refresh_token: str | None
    refresh_min_interval_s: int
    cors_origins: list[str]
    user_agent: str


def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return Settings(
        db_path=Path(os.getenv("DB_PATH", "data/centinela.db")),
        ingest_interval_min=int(os.getenv("INGEST_INTERVAL_MIN", "15")),
        scheduler_enabled=_as_bool(os.getenv("SCHEDULER_ENABLED"), True),
        refresh_token=os.getenv("REFRESH_TOKEN") or None,
        refresh_min_interval_s=int(os.getenv("REFRESH_MIN_INTERVAL_S", "300")),
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        user_agent=os.getenv("USER_AGENT", "centinela/1.0 (proyecto de portafolio)"),
    )
