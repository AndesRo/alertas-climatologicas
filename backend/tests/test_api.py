from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.demo import build_demo_snapshot
from app.locations import LOCATIONS
from app.main import create_app
from app.service import NoDataError


class FakeService:
    def __init__(self, snapshot=None, error=None):
        self.snapshot, self.error, self.calls = snapshot, error, 0

    async def get(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.snapshot


@pytest.fixture
def snapshot():
    return build_demo_snapshot(now=datetime(2026, 10, 15, 15, 0, tzinfo=timezone.utc), cache_ttl_s=600)


@pytest.fixture
def client(snapshot):
    with TestClient(create_app(Settings(), FakeService(snapshot))) as c:
        yield c


def test_health_is_never_cached(client):
    response = client.get("/api/health")
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_overview_has_everything_the_ui_needs(client):
    data = client.get("/api/overview").json()
    assert set(data) == {"generated_at", "demo", "cache_ttl_s", "sources", "locations", "alerts", "quakes", "forecasts"}
    assert len(data["locations"]) == len(LOCATIONS) == len(data["forecasts"])
    assert data["demo"] is True


def test_data_endpoints_are_cdn_cacheable(client):
    for path in ("/api/overview", "/api/alerts", "/api/quakes", "/api/locations", "/api/status", "/api/forecast/santiago"):
        header = client.get(path).headers["cache-control"]
        assert header == "public, max-age=60, s-maxage=600, stale-while-revalidate=3600", path


def test_cache_headers_follow_the_configured_ttl(snapshot):
    with TestClient(create_app(Settings(cache_ttl_s=300), FakeService(snapshot))) as c:
        assert "s-maxage=300, stale-while-revalidate=1800" in c.get("/api/overview").headers["cache-control"]


def test_alert_filters(client):
    all_alerts = client.get("/api/alerts").json()
    reds = client.get("/api/alerts?min_severity=red").json()
    quakes = client.get("/api/alerts?kind=earthquake").json()
    assert reds and all(a["severity"] == "red" for a in reds)
    assert quakes and all(a["kind"] == "earthquake" for a in quakes)
    assert len(all_alerts) > len(reds)
    assert client.get("/api/alerts?kind=bogus").status_code == 422


def test_locations_and_quakes(client):
    rows = {r["id"]: r for r in client.get("/api/locations").json()}
    assert rows["punta-arenas"]["severity"] == "red" and rows["santiago"]["severity"] == "none"
    quakes = client.get("/api/quakes").json()
    assert quakes[0]["source"] == "csn" and quakes[0]["usgs_magnitude"] == 6.2


def test_forecast_endpoint(client):
    data = client.get("/api/forecast/punta-arenas").json()
    assert data["location"]["name"] == "Punta Arenas"
    assert len(data["hourly"]["time"]) == len(data["hourly"]["gust_kmh"]) == 54
    assert {"wind", "snow"} <= {a["kind"] for a in data["alerts"]}
    assert client.get("/api/forecast/atlantida").status_code == 404


def test_status_and_rules(client):
    status = client.get("/api/status").json()
    assert status["locations"] == len(LOCATIONS) and status["alerts"] > 0 and status["demo"] is True
    assert client.get("/api/rules").json()["wind_gust_kmh"] == {"yellow": 60, "orange": 75, "red": 90}


def test_no_data_returns_503_that_is_not_cached():
    with TestClient(create_app(Settings(), FakeService(error=NoDataError("x")))) as c:
        for path in ("/api/overview", "/api/alerts", "/api/forecast/santiago"):
            response = c.get(path)
            assert response.status_code == 503, path
            assert response.headers["cache-control"] == "no-store"
            assert "no responden" in response.json()["detail"]


def test_cors_allows_the_configured_origin_only(snapshot):
    settings = Settings(cors_origins=("https://mi-app.vercel.app",))
    with TestClient(create_app(settings, FakeService(snapshot))) as c:
        ok = c.get("/api/health", headers={"Origin": "https://mi-app.vercel.app"})
        other = c.get("/api/health", headers={"Origin": "https://malo.example"})
    assert ok.headers["access-control-allow-origin"] == "https://mi-app.vercel.app"
    assert "access-control-allow-origin" not in other.headers
