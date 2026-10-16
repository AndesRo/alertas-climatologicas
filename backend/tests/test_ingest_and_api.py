import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import clients
from app.config import Settings
from app.db import Database
from app.ingest import IngestResult, run_ingest
from app.locations import LOCATIONS
from app.main import create_app

from .helpers import NOW, open_meteo_item, usgs_sample


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(clients, "RETRY_BACKOFF_S", 0)


def make_settings(tmp_path, token: str | None = "secret") -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        ingest_interval_min=15,
        scheduler_enabled=False,
        refresh_token=token,
        refresh_min_interval_s=300,
        cors_origins=["http://localhost:5173"],
        user_agent="tests",
    )


def upstream(*, open_meteo_ok=True, usgs_ok=True):
    """Transporte falso: el primer punto (Arica) tiene ráfagas de 95 km/h a las 14:00."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.open-meteo.com":
            if not open_meteo_ok:
                return httpx.Response(500)
            items = [open_meteo_item(gust_kmh={14: 95}) if i == 0 else open_meteo_item() for i in range(len(LOCATIONS))]
            return httpx.Response(200, json=items)
        if request.url.host == "earthquake.usgs.gov":
            return httpx.Response(200, json=usgs_sample()) if usgs_ok else httpx.Response(500)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ingest(db, settings, **kw):
    async def go():
        async with upstream(**kw) as client:
            return await run_ingest(db, settings, client=client, now=NOW)

    return asyncio.run(go())


# --- ingesta ----------------------------------------------------------------
def test_ingest_stores_snapshots_quakes_and_alerts(tmp_path):
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    db.init()

    result = ingest(db, settings)

    assert result.ok and result.forecasts == len(LOCATIONS) and result.quakes == 2
    alerts = {a.key: a for a in db.get_alerts()}
    assert alerts["wind:arica"].severity == "red"
    assert alerts["earthquake:us7000test1"].location_id == "valparaiso"
    assert db.get_meta("last_ingest_at") is not None
    assert db.get_meta("last_error") == ""


def test_ingest_keeps_previous_data_when_a_source_fails(tmp_path):
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    db.init()
    ingest(db, settings)

    result = ingest(db, settings, open_meteo_ok=False)

    assert not result.ok and "open-meteo" in result.errors[0]
    assert len(db.get_snapshots()) == len(LOCATIONS)  # se conservan los datos previos
    assert any(a.key == "wind:arica" for a in db.get_alerts())
    assert "open-meteo" in (db.get_meta("last_error") or "")


def test_ingest_with_every_source_down_does_not_crash(tmp_path):
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    db.init()

    result = ingest(db, settings, open_meteo_ok=False, usgs_ok=False)

    assert not result.ok and len(result.errors) == 2 and result.alerts == 0
    assert db.get_meta("last_ingest_at") is None


# --- API --------------------------------------------------------------------
@pytest.fixture
def seeded(tmp_path):
    settings = make_settings(tmp_path)
    db = Database(settings.db_path)
    db.init()
    ingest(db, settings)
    with TestClient(create_app(settings)) as client:
        yield client


def test_health(seeded):
    assert seeded.get("/api/health").json() == {"status": "ok"}


def test_locations_include_current_conditions_and_severity(seeded):
    rows = {r["id"]: r for r in seeded.get("/api/locations").json()}
    assert len(rows) == len(LOCATIONS)
    assert rows["arica"]["severity"] == "red" and rows["arica"]["alert_count"] == 1
    assert rows["valparaiso"]["severity"] == "orange"  # por el sismo cercano
    assert rows["santiago"]["severity"] == "none"
    assert rows["santiago"]["current"]["temperature_c"] == 14.2


def test_alerts_filters(seeded):
    all_alerts = seeded.get("/api/alerts").json()
    assert [a["severity"] for a in all_alerts] == ["red", "orange"]
    assert [a["kind"] for a in seeded.get("/api/alerts?kind=earthquake").json()] == ["earthquake"]
    assert [a["kind"] for a in seeded.get("/api/alerts?min_severity=red").json()] == ["wind"]
    assert seeded.get("/api/alerts?kind=bogus").status_code == 422


def test_quakes_endpoint(seeded):
    quakes = seeded.get("/api/quakes").json()
    assert [q["id"] for q in quakes] == ["us7000test1", "us7000test2"]


def test_forecast_endpoint_and_errors(seeded):
    data = seeded.get("/api/forecast/arica").json()
    assert data["location"]["name"] == "Arica"
    assert len(data["hourly"]["time"]) == len(data["hourly"]["gust_kmh"]) == 54
    assert [a["kind"] for a in data["alerts"]] == ["wind"]
    assert seeded.get("/api/forecast/atlantida").status_code == 404


def test_forecast_returns_503_before_first_ingest(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        assert client.get("/api/forecast/arica").status_code == 503
        assert client.get("/api/status").json()["last_ingest_at"] is None


def test_status_and_rules(seeded):
    status = seeded.get("/api/status").json()
    assert status["alerts"] == 2 and status["quakes"] == 2 and status["last_error"] is None
    rules = seeded.get("/api/rules").json()
    assert rules["wind_gust_kmh"] == {"yellow": 60, "orange": 75, "red": 90}


# --- /api/refresh -----------------------------------------------------------
def test_refresh_is_disabled_without_token(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, token=None))) as client:
        assert client.post("/api/refresh").status_code == 403


def test_refresh_rejects_bad_token(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        assert client.post("/api/refresh", headers={"X-Refresh-Token": "nope"}).status_code == 401
        assert client.post("/api/refresh").status_code == 401


def test_refresh_runs_ingest_then_skips_when_called_again(tmp_path, monkeypatch):
    calls = []

    async def fake_run_ingest(db, settings, **kw):
        calls.append(1)
        # La ventana anti-abuso compara contra la hora real, igual que la ingesta de verdad.
        db.set_meta("last_attempt_at", datetime.now(timezone.utc).isoformat())
        return IngestResult(ok=True, forecasts=19, quakes=2, alerts=3)

    monkeypatch.setattr("app.main.run_ingest", fake_run_ingest)

    with TestClient(create_app(make_settings(tmp_path))) as client:
        headers = {"X-Refresh-Token": "secret"}
        first = client.post("/api/refresh", headers=headers).json()
        second = client.post("/api/refresh", headers=headers).json()

    assert first["status"] == "ok" and first["alerts"] == 3
    assert second["status"] == "skipped"
    assert len(calls) == 1
