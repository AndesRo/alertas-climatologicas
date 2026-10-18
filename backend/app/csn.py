"""Sismos del Centro Sismológico Nacional (Universidad de Chile).

El CSN no ofrece una API pública oficial. Se usa el espejo comunitario gratuito de Gael Cloud, que
republica sus últimos sismos (https://api.gael.cloud). Condiciones que importan:

* Es de uso no comercial y banea la IP si se hacen más de 9 peticiones en 10 segundos.
* Devuelve solo los ~15 sismos más recientes, de cualquier magnitud.
* No trae coordenadas, solo una referencia en texto ("17 km al SO de Pichidangui").

Por eso el CSN se usa para **confirmar** los sismos que USGS ya ubicó en el mapa: cuando ambos
coinciden en hora y magnitud, se adopta la magnitud oficial del CSN y su referencia geográfica en
español, y las coordenadas se toman de USGS.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .clients import UpstreamError, get_json
from .models import CsnEvent, Quake

CSN_URL = "https://api.gael.cloud/general/public/sismos"

# Dos registros son el mismo sismo si el instante de origen difiere poco y la magnitud es parecida
# (USGS y CSN usan escalas distintas, de ahí la tolerancia).
MATCH_WINDOW_S = 90
MATCH_MAGNITUDE_DELTA = 0.8

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")

try:
    _CHILE_TZ: timezone | ZoneInfo = ZoneInfo("America/Santiago")
except ZoneInfoNotFoundError:  # sin base de datos de zonas horarias: aproximación de verano
    _CHILE_TZ = timezone(timedelta(hours=-3))


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER.search(str(value))
    return float(match.group().replace(",", ".")) if match else None


def _parse_update(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _event_time(raw: Any, updated: datetime | None) -> datetime | None:
    """Interpreta `Fecha`, que no declara zona horaria.

    En la práctica viene en UTC. Como la documentación no lo garantiza, se verifica con
    `FechaUpdate` (UTC): un sismo no puede ocurrir después de haberse publicado. Si leído como UTC
    quedaría en el futuro, se interpreta como hora de Chile.
    """
    try:
        naive = datetime.strptime(str(raw).strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    as_utc = naive.replace(tzinfo=timezone.utc)
    if updated is not None and as_utc - updated > timedelta(minutes=5):
        return naive.replace(tzinfo=_CHILE_TZ).astimezone(timezone.utc)
    return as_utc


def parse_csn(data: Any) -> list[CsnEvent]:
    if not isinstance(data, list):
        raise UpstreamError("CSN: formato inesperado")
    events: list[CsnEvent] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        when = _event_time(row.get("Fecha"), _parse_update(row.get("FechaUpdate")))
        magnitude = _number(row.get("Magnitud"))
        reference = str(row.get("RefGeografica") or "").strip()
        if when is None or magnitude is None or not reference:
            continue
        events.append(
            CsnEvent(
                time_ms=int(when.timestamp() * 1000),
                magnitude=magnitude,
                depth_km=_number(row.get("Profundidad")),
                reference=reference,
            )
        )
    return sorted(events, key=lambda e: e.time_ms, reverse=True)


async def fetch_csn(client: httpx.AsyncClient) -> list[CsnEvent]:
    return parse_csn(await get_json(client, CSN_URL, label="CSN (Gael Cloud)"))


def merge_csn(quakes: Sequence[Quake], events: Sequence[CsnEvent]) -> tuple[list[Quake], int]:
    """Devuelve los sismos de USGS, con los datos oficiales del CSN donde coinciden, y cuántos coincidieron.

    Cada evento del CSN se asigna a lo más a un sismo de USGS (el más cercano en el tiempo).
    """
    window_ms = MATCH_WINDOW_S * 1000
    candidates: list[tuple[int, int, int]] = []  # (diferencia de tiempo, índice de sismo, índice de evento)
    for qi, q in enumerate(quakes):
        for ei, e in enumerate(events):
            dt = abs(q.time_ms - e.time_ms)
            if dt <= window_ms and abs(q.magnitude - e.magnitude) <= MATCH_MAGNITUDE_DELTA:
                candidates.append((dt, qi, ei))

    used_quakes: set[int] = set()
    used_events: set[int] = set()
    matches: dict[int, CsnEvent] = {}
    for _, qi, ei in sorted(candidates):
        if qi in used_quakes or ei in used_events:
            continue
        used_quakes.add(qi)
        used_events.add(ei)
        matches[qi] = events[ei]

    merged: list[Quake] = []
    for qi, q in enumerate(quakes):
        event = matches.get(qi)
        if event is None:
            merged.append(q)
            continue
        merged.append(
            q.model_copy(
                update={
                    "magnitude": event.magnitude,
                    "usgs_magnitude": q.magnitude,
                    "place": event.reference,
                    "depth_km": event.depth_km if event.depth_km is not None else q.depth_km,
                    "source": "csn",
                }
            )
        )
    return merged, len(matches)
