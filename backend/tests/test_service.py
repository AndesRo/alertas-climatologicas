import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import clients, service
from app.config import Settings
from app.demo import build_demo_snapshot
from app.locations import LOCATIONS
from app.service import NoDataError, SnapshotService

from .helpers import NOW, csn_sample, dmc_sample, open_meteo_item, usgs_sample

CHILE_FIRST = LOCATIONS[0].id  # Arica: en estas pruebas tiene ráfagas de 95 km/h a las 14:00


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(clients, "RETRY_BACKOFF_S", 0)


class Upstream:
    """Servidor falso de las APIs externas, con interruptores para simular caídas y contar llamadas."""

    def __init__(self):
        self.down: set[str] = set()
        self.hang: set[str] = set()
        self.calls: dict[str, int] = {}

    def client_factory(self):
        def handler_name(host: str) -> str:
            return {"api.open-meteo.com": "open_meteo", "earthquake.usgs.gov": "usgs",
                    "api.gael.cloud": "csn", "climatologia.meteochile.gob.cl": "dmc"}.get(host, host)

        async def handle(request: httpx.Request) -> httpx.Response:
            name = handler_name(request.url.host)
            self.calls[name] = self.calls.get(name, 0) + 1
            if name in self.hang:
                await asyncio.sleep(30)
            if name in self.down:
                return httpx.Response(500)
            if name == "open_meteo":
                items = [open_meteo_item(gust_kmh={14: 95}) if i == 0 else open_meteo_item() for i in range(len(LOCATIONS))]
                return httpx.Response(200, json=items)
            if name == "usgs":
                return httpx.Response(200, json=usgs_sample())
            if name == "csn":
                return httpx.Response(200, json=csn_sample())
            if name == "dmc":
                return httpx.Response(200, json=dmc_sample())
            return httpx.Response(404)

        return lambda user_agent: httpx.AsyncClient(transport=httpx.MockTransport(handle))


class Clock:
    """Reloj de pared controlable: reemplaza `service.datetime` para avanzar el tiempo sin esperar.

    El reloj monotónico (el que usaba la caché antes) no se ve afectado, así que estas pruebas
    reproducen un portátil suspendido o una función serverless congelada.
    """

    def __init__(self, start: datetime = NOW):
        self.now = start

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)

    def install(self, monkeypatch) -> "Clock":
        monkeypatch.setattr(service, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: self.now)}))
        return self


def make_service(monkeypatch, upstream: Upstream, **settings) -> SnapshotService:
    monkeypatch.setattr(service, "make_client", upstream.client_factory())
    monkeypatch.setattr(service, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    return SnapshotService(Settings(**settings))


def run(coro):
    return asyncio.run(coro)


def by_id(snapshot):
    return {s.id: s for s in snapshot.sources}


# --- armado del snapshot --------------------------------------------------------
def test_snapshot_combines_all_sources(monkeypatch):
    svc = make_service(monkeypatch, Upstream(), dmc_user="yo@correo.cl", dmc_token="t")
    snap = run(svc.get())

    assert snap.generated_at == "2026-10-15T13:00:00+00:00" and not snap.demo
    assert [s.id for s in snap.sources] == ["open_meteo", "usgs", "csn", "dmc"]
    assert all(s.ok and s.enabled for s in snap.sources)
    assert "1 sismo(s) confirmado(s)" in by_id(snap)["csn"].detail

    alerts = {a.key: a for a in snap.alerts}
    assert alerts[f"wind:{CHILE_FIRST}"].severity == "red"
    quake_alert = alerts["earthquake:us7000test1"]
    assert quake_alert.location_id == "valparaiso" and "48 km al O de Valparaíso" in quake_alert.message
    assert snap.quakes[0].source == "csn" and snap.quakes[0].magnitude == 6.0

    santiago = next(l for l in snap.locations if l.id == "santiago")
    assert santiago.observation and santiago.observation.station == "Quinta Normal, Santiago"
    assert santiago.current and santiago.severity == "none"
    assert len(snap.forecasts) == len(LOCATIONS)


def test_dmc_is_disabled_without_credentials(monkeypatch):
    upstream = Upstream()
    snap = run(make_service(monkeypatch, upstream).get())
    dmc = by_id(snap)["dmc"]
    assert (dmc.enabled, dmc.ok) == (False, False)
    assert "dmc" not in upstream.calls
    assert all(l.observation is None for l in snap.locations)


# --- resiliencia ---------------------------------------------------------------
def test_one_failing_source_does_not_break_the_others(monkeypatch):
    upstream = Upstream()
    upstream.down.add("csn")
    snap = run(make_service(monkeypatch, upstream).get())
    csn = by_id(snap)["csn"]
    assert not csn.ok and not csn.stale and "HTTP 500" in csn.detail
    assert by_id(snap)["open_meteo"].ok and snap.alerts
    assert snap.quakes[0].source == "usgs"  # sin CSN no hay confirmación, pero el sismo sigue


def test_failed_source_reuses_last_good_data_and_is_marked_stale(monkeypatch):
    upstream = Upstream()
    svc = make_service(monkeypatch, upstream, cache_ttl_s=0)
    first = run(svc.get())
    assert len(first.quakes) == 2

    upstream.down.add("usgs")
    second = run(svc.get())
    usgs = by_id(second)["usgs"]
    assert (usgs.ok, usgs.stale) == (False, True) and usgs.count == 2
    assert len(second.quakes) == 2  # se conservan los sismos de la lectura anterior


def test_all_sources_down_raises_when_there_is_nothing_to_show(monkeypatch):
    upstream = Upstream()
    upstream.down.update({"open_meteo", "usgs", "csn"})
    with pytest.raises(NoDataError):
        run(make_service(monkeypatch, upstream).get())


def test_all_sources_down_serves_the_previous_snapshot(monkeypatch):
    upstream = Upstream()
    svc = make_service(monkeypatch, upstream, cache_ttl_s=0)
    first = run(svc.get())
    upstream.down.update({"open_meteo", "usgs", "csn"})
    # Con todas caídas pero con datos previos, `_build` los reutiliza como obsoletos (no lanza).
    second = run(svc.get())
    assert all(s.stale for s in second.sources if s.enabled) and second.alerts == first.alerts


def test_a_hanging_source_times_out_without_blocking_the_rest(monkeypatch):
    upstream = Upstream()
    upstream.hang.add("csn")
    svc = make_service(monkeypatch, upstream, build_timeout_s=0.3)
    snap = run(svc.get())
    csn = by_id(snap)["csn"]
    assert not csn.ok and csn.detail == "tiempo de espera agotado"
    assert by_id(snap)["open_meteo"].ok and by_id(snap)["usgs"].ok


# --- caché ---------------------------------------------------------------------
def test_snapshot_is_cached_within_ttl_and_shared_by_concurrent_requests(monkeypatch):
    upstream = Upstream()
    svc = make_service(monkeypatch, upstream, cache_ttl_s=600)

    async def burst():
        return await asyncio.gather(*(svc.get() for _ in range(5)))

    results = run(burst())
    assert all(r is results[0] for r in results)
    assert upstream.calls["open_meteo"] == 1 and upstream.calls["usgs"] == 1

    run(svc.get())
    assert upstream.calls["open_meteo"] == 1  # sigue dentro del TTL


def test_snapshot_is_rebuilt_after_ttl(monkeypatch):
    upstream = Upstream()
    svc = make_service(monkeypatch, upstream, cache_ttl_s=0)
    run(svc.get())
    run(svc.get())
    assert upstream.calls["open_meteo"] == 2


def test_cache_expires_with_the_wall_clock_even_if_the_process_was_asleep(monkeypatch):
    """Caso real: servidor local en un portátil que se suspendió, o función serverless congelada."""
    upstream = Upstream()
    svc = make_service(monkeypatch, upstream, cache_ttl_s=600)
    clock = Clock().install(monkeypatch)

    first = run(svc.get())
    clock.advance(minutes=5)
    assert run(svc.get()) is first  # dentro del TTL se reutiliza
    assert upstream.calls["open_meteo"] == 1

    clock.advance(days=2)
    second = run(svc.get())
    assert upstream.calls["open_meteo"] == 2
    assert second.generated_at != first.generated_at


def test_cache_is_not_trusted_if_the_clock_goes_backwards(monkeypatch):
    upstream = Upstream()
    svc = make_service(monkeypatch, upstream, cache_ttl_s=600)
    clock = Clock().install(monkeypatch)
    run(svc.get())
    clock.advance(hours=-3)
    run(svc.get())
    assert upstream.calls["open_meteo"] == 2


def test_last_good_data_is_only_reused_up_to_the_stale_limit(monkeypatch):
    upstream = Upstream()
    svc = make_service(monkeypatch, upstream, cache_ttl_s=600)
    clock = Clock().install(monkeypatch)
    run(svc.get())
    upstream.down.add("usgs")

    clock.advance(hours=5)  # dentro del límite: se muestra como obsoleto
    usgs = by_id(run(svc.get()))["usgs"]
    assert (usgs.ok, usgs.stale, usgs.count) == (False, True, 2)

    clock.advance(hours=2)  # 7 h desde la última lectura buena: ya no describe el presente
    snap = run(svc.get())
    usgs = by_id(snap)["usgs"]
    assert (usgs.ok, usgs.stale) == (False, False)
    assert snap.quakes == [] and by_id(snap)["open_meteo"].ok


def test_all_sources_down_too_long_is_an_error_instead_of_ancient_data(monkeypatch):
    upstream = Upstream()
    svc = make_service(monkeypatch, upstream, cache_ttl_s=600)
    clock = Clock().install(monkeypatch)
    run(svc.get())
    upstream.down.update({"open_meteo", "usgs", "csn"})

    clock.advance(minutes=30)
    assert all(s.stale for s in run(svc.get()).sources if s.enabled)  # media hora: aún sirve

    clock.advance(hours=7)
    with pytest.raises(NoDataError):
        run(svc.get())


# --- demo ----------------------------------------------------------------------
def test_demo_mode_needs_no_network_and_is_flagged(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("el modo demo no debe usar la red")

    monkeypatch.setattr(service, "make_client", boom)
    snap = run(SnapshotService(Settings(demo_mode=True)).get())
    assert snap.demo and len(snap.alerts) >= 8
    assert {a.severity for a in snap.alerts} == {"yellow", "orange", "red"}
    assert snap.quakes[0].source == "csn"


def test_demo_snapshot_is_pure(monkeypatch):
    now = datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc)
    a = build_demo_snapshot(now=now, cache_ttl_s=600)
    b = build_demo_snapshot(now=now, cache_ttl_s=600)
    assert a == b
