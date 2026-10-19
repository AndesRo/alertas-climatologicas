"""Capa de precipitación prevista: grilla, cliente, renovación horaria, endpoint y datos de demo."""

import asyncio
import math
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import clients
from app.clients import UpstreamError, fetch_precip_grid
from app.config import Settings
from app.db import Database
from app.grid import ENVELOPE, GRID_POINTS, GRID_STEP_DEG, build_grid
from app.ingest import PRECIP_META_KEY, load_precip, run_precip_ingest
from app.locations import LOCATIONS
from app.main import create_app
from scripts.seed_demo import build_demo_precip

from .helpers import NOW

CHUNKS = math.ceil(len(GRID_POINTS) / clients.PRECIP_CHUNK)
RAIN_INDEX = 13  # NOW es 13:00 UTC: la serie de prueba parte a las 00:00, así que la hora actual es el índice 13


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(clients, "RETRY_BACKOFF_S", 0)


def run(coro):
    return asyncio.run(coro)


def make_settings(tmp_path, **overrides) -> Settings:
    base = dict(
        db_path=tmp_path / "test.db",
        ingest_interval_min=15,
        scheduler_enabled=False,
        refresh_token="secret",
        refresh_min_interval_s=300,
        cors_origins=["http://localhost:5173"],
        user_agent="tests",
    )
    base.update(overrides)
    return Settings(**base)


def precip_item(*, hours: int = 48, first_hour: int = 0, rain: dict[int, float | None] | None = None) -> dict:
    """Un punto con el formato de Open-Meteo (hora UTC, 2 días): seco salvo lo indicado en `rain`."""
    times = [f"2026-10-{15 + (first_hour + h) // 24}T{(first_hour + h) % 24:02d}:00" for h in range(hours)]
    values: list[float | None] = [0.0] * hours
    for index, mm in (rain or {}).items():
        values[index] = mm
    return {"hourly": {"time": times, "precipitation": values}}


class GridUpstream:
    """Open-Meteo falso que solo atiende la grilla, con un interruptor para simular caídas."""

    def __init__(self):
        self.calls = 0
        self.params: list[dict] = []
        self.down = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.params.append(dict(request.url.params))
        if self.down:
            return httpx.Response(500)
        count = len(request.url.params["latitude"].split(","))
        return httpx.Response(200, json=[precip_item(rain={RAIN_INDEX: 2.34}) for _ in range(count)])

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))


# --- grilla ---------------------------------------------------------------------------------------
def test_grid_is_a_band_over_chile_not_a_rectangle():
    lats = {lat for lat, _ in GRID_POINTS}
    lons = [lon for _, lon in GRID_POINTS]
    rectangle = len(lats) * (max(lons) - min(lons) + 1)
    assert 120 <= len(GRID_POINTS) <= 260
    assert len(GRID_POINTS) < 0.6 * rectangle, "una caja sobre Chile desperdiciaría puntos en el océano y Argentina"
    assert min(lats) == -55 and max(lats) == -18


def test_grid_points_are_unique_and_sit_on_whole_degrees():
    assert len(set(GRID_POINTS)) == len(GRID_POINTS)
    assert all(float(lat).is_integer() and float(lon).is_integer() for lat, lon in GRID_POINTS)


def test_every_monitored_city_falls_inside_a_cell():
    half = GRID_STEP_DEG / 2 + 1e-9
    for loc in LOCATIONS:
        assert any(abs(lat - loc.lat) <= half and abs(lon - loc.lon) <= half for lat, lon in GRID_POINTS), loc.name


def test_grid_is_deterministic_and_anchors_run_north_to_south():
    assert build_grid() == GRID_POINTS
    assert ENVELOPE[0][0] > ENVELOPE[-1][0]


# --- cliente --------------------------------------------------------------------------------------
def test_fetch_precip_grid_requests_utc_in_parallel_chunks_and_trims_to_the_current_hour():
    upstream = GridUpstream()

    async def go():
        async with upstream.client() as c:
            return await fetch_precip_grid(c, GRID_POINTS, now=NOW)

    grid = run(go())

    assert upstream.calls == CHUNKS
    assert all(p["hourly"] == "precipitation" and p["timezone"] == "GMT" for p in upstream.params)
    assert all(len(p["latitude"].split(",")) <= clients.PRECIP_CHUNK for p in upstream.params)
    assert len(grid.cells) == len(GRID_POINTS) and grid.step_deg == GRID_STEP_DEG
    assert grid.times[0] == "2026-10-15T13:00" and grid.times[-1] == "2026-10-16T13:00" and len(grid.times) == 25
    assert grid.cells[0].mm[0] == 2.3  # redondeado a un decimal
    assert all(len(c.mm) == 25 for c in grid.cells)
    assert (grid.cells[0].lat, grid.cells[0].lon) == GRID_POINTS[0]
    assert grid.fetched_at == "2026-10-15T13:00:00+00:00" and grid.demo is False


def test_fetch_precip_grid_late_in_the_day_still_returns_a_full_window():
    late = datetime(2026, 10, 15, 23, 30, tzinfo=timezone.utc)

    async def go():
        async with GridUpstream().client() as c:
            return await fetch_precip_grid(c, GRID_POINTS, now=late)

    grid = run(go())
    assert grid.times[0] == "2026-10-15T23:00" and grid.times[-1] == "2026-10-16T23:00" and len(grid.times) == 25


def test_missing_values_stay_null_instead_of_becoming_zero():
    def handler(request):
        count = len(request.url.params["latitude"].split(","))
        return httpx.Response(200, json=[precip_item(rain={RAIN_INDEX: None}) for _ in range(count)])

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_precip_grid(c, GRID_POINTS[:5], now=NOW)

    assert run(go()).cells[0].mm[0] is None


def _fails(handler, match):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await fetch_precip_grid(c, GRID_POINTS, now=NOW)

    with pytest.raises(UpstreamError, match=match):
        run(go())


def test_wrong_number_of_results_is_an_error():
    _fails(lambda r: httpx.Response(200, json=[precip_item()]), "devolvió 1 resultados")


def test_cells_with_different_time_columns_are_an_error():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        count = len(request.url.params["latitude"].split(","))
        # El segundo bloque llega sin la hora en curso (parte a las 14:00): su ventana no coincide con la del primero.
        shifted = precip_item(first_hour=14, hours=34) if calls["n"] == 2 else precip_item()
        return httpx.Response(200, json=[shifted for _ in range(count)])

    _fails(handler, "misma columna de tiempo")


def test_response_that_does_not_reach_the_current_hour_is_an_error():
    def handler(request):
        count = len(request.url.params["latitude"].split(","))
        return httpx.Response(200, json=[precip_item(hours=10) for _ in range(count)])  # solo hasta las 09:00

    _fails(handler, "no incluye la hora actual")


def test_malformed_item_is_an_error():
    _fails(lambda r: httpx.Response(200, json=[{"nada": 1}] * len(r.url.params["latitude"].split(","))), "formato inesperado")


def test_http_errors_are_reported():
    _fails(lambda r: httpx.Response(500), "500")


# --- ingesta de la grilla -------------------------------------------------------------------------
def ingest(db, settings, upstream, *, now=NOW):
    async def go():
        async with upstream.client() as client:
            return await run_precip_ingest(db, settings, client=client, now=now)

    return run(go())


def fresh_db(tmp_path, **overrides):
    settings = make_settings(tmp_path, **overrides)
    db = Database(settings.db_path)
    db.init()
    return db, settings


def test_ingest_stores_the_grid_in_the_database(tmp_path):
    db, settings = fresh_db(tmp_path)
    assert load_precip(db) is None

    assert ingest(db, settings, GridUpstream()) is True

    grid = load_precip(db)
    assert grid is not None and len(grid.cells) == len(GRID_POINTS) and grid.demo is False
    assert db.get_meta("precip_error") == ""


def test_grid_is_not_requested_again_while_it_is_fresh(tmp_path):
    db, settings = fresh_db(tmp_path, precip_ttl_s=3600)
    upstream = GridUpstream()
    assert ingest(db, settings, upstream) is True
    assert upstream.calls == CHUNKS

    # La ingesta general corre cada 15 min, pero la grilla cuesta ~200 llamadas: no debe repetirse antes de tiempo.
    assert ingest(db, settings, upstream, now=NOW + timedelta(minutes=45)) is False
    assert upstream.calls == CHUNKS

    assert ingest(db, settings, upstream, now=NOW + timedelta(minutes=61)) is True
    assert upstream.calls == 2 * CHUNKS


def test_a_failure_keeps_the_previous_grid_and_records_the_error(tmp_path):
    db, settings = fresh_db(tmp_path, precip_ttl_s=0)
    upstream = GridUpstream()
    ingest(db, settings, upstream)
    before = load_precip(db)

    upstream.down = True
    assert ingest(db, settings, upstream, now=NOW + timedelta(hours=1)) is False

    assert load_precip(db) == before
    assert "500" in (db.get_meta("precip_error") or "")


def test_failure_without_any_previous_grid_leaves_the_database_empty(tmp_path):
    db, settings = fresh_db(tmp_path)
    upstream = GridUpstream()
    upstream.down = True
    assert ingest(db, settings, upstream) is False
    assert load_precip(db) is None


def test_corrupt_stored_grid_is_treated_as_missing_and_rebuilt(tmp_path):
    db, settings = fresh_db(tmp_path)
    db.set_meta(PRECIP_META_KEY, "{esto no es json")
    assert load_precip(db) is None
    assert ingest(db, settings, GridUpstream()) is True


# --- endpoint -------------------------------------------------------------------------------------
def test_precip_endpoint_returns_503_before_the_first_read(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.get("/api/precip")
    assert response.status_code == 503
    assert "aún no está disponible" in response.json()["detail"]


def test_precip_endpoint_returns_the_stored_grid(tmp_path):
    db, settings = fresh_db(tmp_path)
    ingest(db, settings, GridUpstream())

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/precip")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    data = response.json()
    assert set(data) == {"fetched_at", "step_deg", "times", "cells", "demo"}
    assert len(data["cells"]) == len(GRID_POINTS) and len(data["times"]) == 25
    assert set(data["cells"][0]) == {"lat", "lon", "mm"}


# --- datos de demo --------------------------------------------------------------------------------
def test_demo_grid_is_pure_flagged_and_has_both_wet_and_dry_cells():
    now = datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc)
    a, b = build_demo_precip(now=now), build_demo_precip(now=now)
    assert a == b and a.demo is True
    assert a.times[0] == "2026-10-15T15:00" and len(a.times) == 25
    values = [v for c in a.cells for v in c.mm if v is not None]
    assert 5 <= max(values) <= 15 and min(values) == 0.0
    assert sum(1 for v in values if v >= 0.1) > 200