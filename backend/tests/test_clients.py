import asyncio

import httpx
import pytest

from app import clients
from app.clients import UpstreamError, fetch_forecasts, fetch_quakes, parse_open_meteo, parse_usgs, trim_hourly
from app.locations import LOCATIONS

from .helpers import CURRENT_TIME, NOW, make_hourly, open_meteo_item, usgs_sample


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(clients, "RETRY_BACKOFF_S", 0)


def client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_parse_open_meteo_maps_fields():
    current, hourly = parse_open_meteo(open_meteo_item(gust_kmh={14: 82}))
    assert current.time == CURRENT_TIME
    assert current.temperature_c == 14.2 and current.weather_code == 2
    assert hourly.gust_kmh[14] == 82
    assert len(hourly.time) == len(hourly.temperature_c) == 72


def test_parse_open_meteo_rejects_unexpected_shape():
    with pytest.raises(UpstreamError):
        parse_open_meteo({"hourly": {}})


def test_trim_hourly_keeps_a_window_around_now():
    trimmed = trim_hourly(make_hourly(), CURRENT_TIME, back=6, ahead=48)
    assert trimmed.time[0] == "2026-10-15T04:00"
    assert len(trimmed.time) == 54
    assert len(trimmed.gust_kmh) == 54


def test_parse_usgs_sorts_newest_first_and_skips_incomplete_features():
    data = usgs_sample()
    data["features"].append({"id": "bad", "properties": {"mag": None, "time": 1}, "geometry": {"coordinates": [0, 0]}})
    quakes = parse_usgs(data)
    assert [q.id for q in quakes] == ["us7000test1", "us7000test2"]
    assert quakes[0].lon == -71.9 and quakes[0].lat == -33.1 and quakes[0].depth_km == 35.0


def test_fetch_forecasts_sends_all_coordinates_in_one_request():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=[open_meteo_item() for _ in LOCATIONS])

    async def go():
        async with client_with(handler) as c:
            return await fetch_forecasts(c, LOCATIONS)

    result = asyncio.run(go())
    assert set(result) == {loc.id for loc in LOCATIONS}
    assert len(seen["params"]["latitude"].split(",")) == len(LOCATIONS)
    assert seen["params"]["timezone"] == "auto"


def test_fetch_forecasts_accepts_single_object_for_single_location():
    async def go():
        async with client_with(lambda r: httpx.Response(200, json=open_meteo_item())) as c:
            return await fetch_forecasts(c, LOCATIONS[:1])

    assert list(asyncio.run(go())) == [LOCATIONS[0].id]


def test_fetch_forecasts_fails_when_result_count_does_not_match():
    async def go():
        async with client_with(lambda r: httpx.Response(200, json=[open_meteo_item()])) as c:
            return await fetch_forecasts(c, LOCATIONS)

    with pytest.raises(UpstreamError):
        asyncio.run(go())


def test_requests_are_retried_before_giving_up():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500) if calls["n"] < 3 else httpx.Response(200, json=usgs_sample())

    async def go():
        async with client_with(handler) as c:
            return await fetch_quakes(c, now=NOW)

    assert len(asyncio.run(go())) == 2
    assert calls["n"] == 3


def test_persistent_failure_raises_upstream_error():
    async def go():
        async with client_with(lambda r: httpx.Response(503)) as c:
            return await fetch_quakes(c, now=NOW)

    with pytest.raises(UpstreamError):
        asyncio.run(go())
