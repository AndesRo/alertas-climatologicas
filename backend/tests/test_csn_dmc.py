import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app import clients
from app.clients import UpstreamError, parse_usgs
from app.csn import fetch_csn, merge_csn, parse_csn
from app.dmc import KNOT_TO_KMH, fetch_dmc, nearest_observation, parse_number, parse_stations
from app.locations import LOCATIONS_BY_ID
from app.models import Quake

from .helpers import NOW_MS, csn_sample, dmc_sample, usgs_sample


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(clients, "RETRY_BACKOFF_S", 0)


def client_with(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def utc_ms(*parts: int) -> int:
    return int(datetime(*parts, tzinfo=timezone.utc).timestamp() * 1000)


# --- CSN: lectura ------------------------------------------------------------
def test_parse_csn_reads_text_fields_and_sorts_newest_first():
    events = parse_csn(csn_sample())
    assert [e.reference for e in events] == ["10 km al E de Mejillones", "48 km al O de Valparaíso"]
    assert events[1].magnitude == 6.0 and events[1].depth_km == 31.0


def test_parse_csn_treats_fecha_as_utc_when_consistent_with_update_time():
    # Fecha 11:59:48 y publicado a las 12:10Z: coherente con UTC.
    event = parse_csn(csn_sample())[1]
    assert event.time_ms == NOW_MS - 3_600_000 - 12_000  # 11:59:48Z; NOW es 13:00Z


def test_parse_csn_falls_back_to_chile_time_when_utc_reading_is_in_the_future():
    # Publicado a las 12:10Z. "09:00" es pasado como UTC: se deja en UTC.
    plausible = {"Fecha": "2026-10-15 09:00:00", "Profundidad": "10", "Magnitud": "5.0",
                 "RefGeografica": "X", "FechaUpdate": "2026-10-15T12:10:00.000Z"}
    # "14:00" como UTC sería posterior a la publicación: es hora de Chile (UTC-3 en octubre), o sea 17:00Z.
    in_the_future = dict(plausible, Fecha="2026-10-15 14:00:00")

    assert parse_csn([plausible])[0].time_ms == utc_ms(2026, 10, 15, 9, 0)
    assert parse_csn([in_the_future])[0].time_ms == utc_ms(2026, 10, 15, 17, 0)


def test_parse_csn_skips_incomplete_rows_and_rejects_bad_payload():
    rows = csn_sample() + [{"Fecha": "ayer", "Magnitud": "3", "RefGeografica": "Y"}, {"Magnitud": "x"}, "basura"]
    assert len(parse_csn(rows)) == 2
    with pytest.raises(UpstreamError):
        parse_csn({"error": "limit"})


def test_parse_csn_tolerates_units_and_decimal_commas_in_magnitude():
    row = dict(csn_sample()[0], Magnitud="3,4 Ml")
    assert parse_csn([row])[0].magnitude == 3.4


# --- CSN: fusión con USGS ------------------------------------------------------
def test_merge_adopts_csn_magnitude_and_reference_but_keeps_usgs_coordinates():
    quakes = parse_usgs(usgs_sample())
    merged, confirmed = merge_csn(quakes, parse_csn(csn_sample()))
    assert confirmed == 1
    top = merged[0]
    assert (top.source, top.magnitude, top.usgs_magnitude) == ("csn", 6.0, 6.2)
    assert top.place == "48 km al O de Valparaíso" and top.depth_km == 31.0
    assert (top.lat, top.lon) == (-33.1, -71.9)  # coordenadas de USGS
    assert merged[1].source == "usgs"  # el M4.8 no tiene par en el CSN


def test_merge_requires_close_time_and_similar_magnitude():
    quake = Quake(id="q", magnitude=6.2, place="p", time_ms=NOW_MS, lat=-33, lon=-71)
    far_in_time = parse_csn([dict(csn_sample()[0], Fecha="2026-10-15 12:50:00")])
    other_magnitude = parse_csn([dict(csn_sample()[0], Fecha="2026-10-15 12:59:59", Magnitud="3.0")])
    assert merge_csn([quake], far_in_time)[1] == 0
    assert merge_csn([quake], other_magnitude)[1] == 0


def test_merge_matches_each_csn_event_to_at_most_one_quake():
    q1 = Quake(id="a", magnitude=5.0, place="a", time_ms=NOW_MS - 10_000, lat=-33, lon=-71)
    q2 = Quake(id="b", magnitude=5.1, place="b", time_ms=NOW_MS + 20_000, lat=-33, lon=-71)
    event = parse_csn([{"Fecha": "2026-10-15 12:59:55", "Magnitud": "5.0", "Profundidad": "9",
                        "RefGeografica": "ref", "FechaUpdate": "2026-10-15T13:05:00Z"}])
    merged, confirmed = merge_csn([q1, q2], event)
    assert confirmed == 1
    assert [q.source for q in merged] == ["csn", "usgs"]  # q1 es el más cercano en el tiempo


def test_fetch_csn_over_http():
    async def go():
        async with client_with(lambda r: httpx.Response(200, json=csn_sample())) as c:
            return await fetch_csn(c)

    assert len(asyncio.run(go())) == 2


# --- DMC ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw, expected",
    [(12, 12.0), ("12.5", 12.5), ("20.2 °C", 20.2), ("65 %", 65.0), ("12,3 kt", 12.3), ("-3.4 °C", -3.4),
     (None, None), ("sin dato", None), (True, None)],
)
def test_parse_number_handles_documented_value_shapes(raw, expected):
    assert parse_number(raw) == expected


def test_parse_stations_converts_knots_and_skips_unusable_features():
    stations = parse_stations(dmc_sample())
    assert [s.name for s in stations] == ["Quinta Normal, Santiago", "Lejos", "Chacalluta, Arica Ap."]
    quinta = stations[0]
    assert quinta.wind_kmh == round(6.5 * KNOT_TO_KMH, 1)  # el viento actual viene en nudos
    assert quinta.wind_max_6h_kmh == 31.0  # el máximo de 6 h ya viene en km/h
    assert (quinta.temperature_c, quinta.humidity_pct) == (18.2, 45.0)
    assert quinta.temp_max_tomorrow_c == 26.0 and quinta.code == "330020"


def test_parse_stations_rejects_unexpected_payloads():
    for bad in ({"status": "token inválido"}, [], {"features": "x"}):
        with pytest.raises(UpstreamError):
            parse_stations(bad)


def test_nearest_observation_uses_closest_useful_station_within_radius():
    stations = parse_stations(dmc_sample())
    santiago = nearest_observation(LOCATIONS_BY_ID["santiago"], stations)
    assert santiago is not None and santiago.station == "Quinta Normal, Santiago"
    assert 0 < santiago.distance_km < 10
    # Chacalluta está a metros de Arica pero no tiene datos útiles; la siguiente está a más de 60 km.
    assert nearest_observation(LOCATIONS_BY_ID["arica"], stations) is None
    assert nearest_observation(LOCATIONS_BY_ID["punta-arenas"], stations) is None


def test_fetch_dmc_sends_credentials_and_never_leaks_them_in_errors():
    seen = {}

    def ok(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json=dmc_sample())

    async def run(handler):
        async with client_with(handler) as c:
            return await fetch_dmc(c, "yo@correo.cl", "TOKEN-SECRETO")

    assert len(asyncio.run(run(ok))) == 3
    assert seen == {"usuario": "yo@correo.cl", "token": "TOKEN-SECRETO"}

    with pytest.raises(UpstreamError) as err:
        asyncio.run(run(lambda r: httpx.Response(401)))
    assert "TOKEN-SECRETO" not in str(err.value) and "yo@correo.cl" not in str(err.value)
    assert "HTTP 401" in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__


def test_client_errors_are_not_retried_but_server_errors_are():
    calls = {"n": 0}

    def handler(status: int):
        def inner(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(status)
        return inner

    async def run(status):
        async with client_with(handler(status)) as c:
            await clients.get_json(c, "https://x.test/", label="X")

    for status, expected_calls in ((403, 1), (503, clients.RETRY_ATTEMPTS)):
        calls["n"] = 0
        with pytest.raises(UpstreamError):
            asyncio.run(run(status))
        assert calls["n"] == expected_calls
