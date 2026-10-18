"""Capa de precipitación prevista: grilla, cliente, caché del servicio, endpoint y datos de demo."""

import asyncio
import math
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import clients, service
from app.clients import UpstreamError, fetch_precip_grid
from app.config import Settings
from app.demo import build_demo_precip
from app.grid import ENVELOPE, GRID_POINTS, GRID_STEP_DEG, build_grid
from app.locations import LOCATIONS
from app.main import create_app
from app.service import NoDataError, SnapshotService

from .helpers import NOW
from .test_service import Clock, Upstream, make_service as make_overview_service

CHUNKS = math.ceil(len(GRID_POINTS) / clients.PRECIP_CHUNK)
RAIN_INDEX = 13  # NOW es 13:00 UTC: la serie de prueba parte a las 00:00, así que la hora actual es el índice 13


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(clients, "RETRY_BACKOFF_S", 0)


def run(coro):
    return asyncio.run(coro)


def precip_item(*, hours: int = 48, first_hour: int = 0, rain: dict[int, float | None] | None = None) -> dict:
    """Un punto con el formato de Open-Meteo (hora UTC, 2 días): seco salvo lo indicado en `rain`."""
    times = [f"2026-10-{15 + (first_hour + h) // 24}T{(first_hour + h) % 24:02d}:00" for h in range(hours)]
    values: list[float | None] = [0.0] * hours
    for index, mm in (rain or {}).items():
        values[index] = mm
    return {"hourly": {"time": times, "precipitation": values}}


class GridUpstream:
    """Open-Meteo falso que solo atiende la grilla, con interruptores para simular caídas."""

    def __init__(self):
        self.calls = 0
        self.params: list[dict] = []
        self.down = False
        self.hang = False

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.params.append(dict(request.url.params))
        if self.hang:
            await asyncio.sleep(30)
        if self.down:
            return httpx.Response(500)
        count = len(request.url.params["latitude"].split(","))
        return httpx.Response(200, json=[precip_item(rain={RAIN_INDEX: 2.34}) for _ in range(count)])

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))


def make_service(monkeypatch, upstream: GridUpstream, **settings) -> SnapshotService:
    monkeypatch.setattr(service, "make_client", lambda user_agent: upstream.client())
    monkeypatch.setattr(service, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    return SnapshotService(Settings(**settings))


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


def test_grid_is_deterministic_and_rejects_latitudes_outside_the_envelope():
    assert build_grid() == GRID_POINTS
    assert ENVELOPE[0][0] > ENVELOPE[-1][0], "los anclajes van de norte a sur"


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

    with pytest.raises(UpstreamError, match=match) as info:
        run(go())
    assert "api.open-meteo.com" not in str(info.value), "el mensaje no debe filtrar la URL"


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


def test_http_errors_are_reported_without_the_url():
    _fails(lambda r: httpx.Response(500), "HTTP 500")


# --- servicio: caché y resiliencia ----------------------------------------------------------------
def test_grid_is_cached_within_its_ttl_and_shared_by_concurrent_requests(monkeypatch):
    upstream = GridUpstream()
    svc = make_service(monkeypatch, upstream, precip_ttl_s=3600)

    async def burst():
        return await asyncio.gather(*(svc.get_precip() for _ in range(5)))

    grids = run(burst())
    assert all(g is grids[0] for g in grids)
    assert upstream.calls == CHUNKS

    run(svc.get_precip())
    assert upstream.calls == CHUNKS  # sigue dentro del TTL: no se vuelve a gastar cupo de Open-Meteo


def test_grid_is_rebuilt_after_its_ttl(monkeypatch):
    upstream = GridUpstream()
    svc = make_service(monkeypatch, upstream, precip_ttl_s=0)
    run(svc.get_precip())
    run(svc.get_precip())
    assert upstream.calls == 2 * CHUNKS


def test_grid_expires_with_the_wall_clock_even_if_the_process_was_asleep(monkeypatch):
    """Una grilla vencida no puede seguir sirviéndose: el frontend la descarta y la capa desaparece."""
    upstream = GridUpstream()
    svc = make_service(monkeypatch, upstream, precip_ttl_s=3600)
    clock = Clock().install(monkeypatch)

    first = run(svc.get_precip())
    clock.advance(minutes=30)
    assert run(svc.get_precip()) is first
    assert upstream.calls == CHUNKS

    clock.advance(hours=2)  # el reloj monotónico no se entera de este salto
    second = run(svc.get_precip())
    assert second is not first and second.fetched_at != first.fetched_at
    assert upstream.calls == 2 * CHUNKS


def test_previous_grid_is_not_served_once_it_is_too_old(monkeypatch):
    upstream = GridUpstream()
    svc = make_service(monkeypatch, upstream, precip_ttl_s=3600)
    clock = Clock().install(monkeypatch)
    first = run(svc.get_precip())
    upstream.down = True

    clock.advance(hours=2)  # la fuente cayó: sirve la anterior, que aún es razonable
    assert run(svc.get_precip()) is first

    clock.advance(hours=5)  # 7 h desde la última lectura buena
    with pytest.raises(NoDataError):
        run(svc.get_precip())


def test_failure_without_any_previous_grid_raises(monkeypatch):
    upstream = GridUpstream()
    upstream.down = True
    with pytest.raises(NoDataError, match="HTTP 500"):
        run(make_service(monkeypatch, upstream).get_precip())


def test_failure_after_a_good_read_serves_the_previous_grid(monkeypatch):
    upstream = GridUpstream()
    svc = make_service(monkeypatch, upstream, precip_ttl_s=0)
    first = run(svc.get_precip())
    upstream.down = True
    assert run(svc.get_precip()) is first


def test_a_hanging_source_times_out(monkeypatch):
    upstream = GridUpstream()
    upstream.hang = True
    svc = make_service(monkeypatch, upstream, build_timeout_s=0.3)
    with pytest.raises(NoDataError, match="tiempo de espera agotado"):
        run(svc.get_precip())


def test_demo_mode_serves_a_synthetic_grid_without_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("el modo demo no debe usar la red")

    monkeypatch.setattr(service, "make_client", boom)
    grid = run(SnapshotService(Settings(demo_mode=True)).get_precip())
    assert grid.demo is True and len(grid.cells) == len(GRID_POINTS)


def test_the_overview_never_requests_the_grid(monkeypatch):
    """La grilla cuesta ~200 llamadas a Open-Meteo: no puede colarse en la lectura que se renueva cada 10 min."""
    upstream = Upstream()
    run(make_overview_service(monkeypatch, upstream).get())
    assert upstream.calls["open_meteo"] == 1


# --- endpoint -------------------------------------------------------------------------------------
class FakeService:
    def __init__(self, grid=None, error=None):
        self.grid, self.error = grid, error

    async def get_precip(self):
        if self.error:
            raise self.error
        return self.grid


@pytest.fixture
def demo_grid():
    return build_demo_precip(now=datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc))


def test_precip_endpoint_returns_the_grid_with_hourly_cdn_caching(demo_grid):
    with TestClient(create_app(Settings(), FakeService(demo_grid))) as c:
        response = c.get("/api/precip")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300, s-maxage=3600, stale-while-revalidate=21600"
    data = response.json()
    assert set(data) == {"fetched_at", "step_deg", "times", "cells", "demo"}
    assert len(data["cells"]) == len(GRID_POINTS) and len(data["times"]) == 25
    assert set(data["cells"][0]) == {"lat", "lon", "mm"}


def test_precip_cache_follows_the_configured_ttl(demo_grid):
    with TestClient(create_app(Settings(precip_ttl_s=1800), FakeService(demo_grid))) as c:
        assert "s-maxage=1800, stale-while-revalidate=10800" in c.get("/api/precip").headers["cache-control"]


def test_precip_unavailable_returns_503_that_is_not_cached():
    with TestClient(create_app(Settings(), FakeService(error=NoDataError("x")))) as c:
        response = c.get("/api/precip")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "no está disponible" in response.json()["detail"]


# --- datos de demo --------------------------------------------------------------------------------
def test_demo_grid_is_pure_flagged_and_has_both_wet_and_dry_cells():
    now = datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc)
    a, b = build_demo_precip(now=now), build_demo_precip(now=now)
    assert a == b and a.demo is True
    assert a.times[0] == "2026-10-15T15:00" and len(a.times) == 25
    values = [v for c in a.cells for v in c.mm if v is not None]
    assert 5 <= max(values) <= 15 and min(values) == 0.0
    assert sum(1 for v in values if v >= 0.1) > 200
