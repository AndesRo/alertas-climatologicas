from app.locations import LOCATIONS, LOCATIONS_BY_ID
from app.models import Quake
from app.rules import (
    FROST_C,
    GUST_KMH,
    classify,
    evaluate_location,
    evaluate_quakes,
    forecast_window,
    haversine_km,
    max_severity,
)

from .helpers import CURRENT_TIME, NOW_MS, make_hourly

SANTIAGO = LOCATIONS_BY_ID["santiago"]


def kinds(alerts):
    return {a.kind: a.severity for a in alerts}


# --- classify ---------------------------------------------------------------
def test_classify_ascending_thresholds():
    assert classify(59.9, GUST_KMH) is None
    assert classify(60, GUST_KMH) == "yellow"
    assert classify(75, GUST_KMH) == "orange"
    assert classify(120, GUST_KMH) == "red"


def test_classify_descending_thresholds_for_frost():
    assert classify(0.1, FROST_C, lower_is_worse=True) is None
    assert classify(0, FROST_C, lower_is_worse=True) == "yellow"
    assert classify(-3, FROST_C, lower_is_worse=True) == "orange"
    assert classify(-10, FROST_C, lower_is_worse=True) == "red"


def test_haversine_santiago_valparaiso_is_about_100_km():
    valpo = LOCATIONS_BY_ID["valparaiso"]
    d = haversine_km(SANTIAGO.lat, SANTIAGO.lon, valpo.lat, valpo.lon)
    assert 90 < d < 110


# --- ventana de pronóstico --------------------------------------------------
def test_forecast_window_starts_at_current_hour_and_respects_horizon():
    h = make_hourly()
    idx = forecast_window(h, CURRENT_TIME, horizon_hours=24)
    assert idx[0] == 10
    assert len(idx) == 24
    assert idx[-1] == 33


# --- alertas meteorológicas -------------------------------------------------
def test_calm_weather_produces_no_alerts():
    assert evaluate_location(SANTIAGO, CURRENT_TIME, make_hourly()) == []


def test_strong_gusts_raise_orange_wind_alert_with_peak_time():
    alerts = evaluate_location(SANTIAGO, CURRENT_TIME, make_hourly(gust_kmh={14: 82}))
    assert kinds(alerts) == {"wind": "orange"}
    a = alerts[0]
    assert a.value == 82
    assert a.unit == "km/h"
    assert "82 km/h" in a.message and "hoy a las 14:00" in a.message


def test_alert_for_tomorrow_says_manana():
    alerts = evaluate_location(SANTIAGO, CURRENT_TIME, make_hourly(gust_kmh={30: 95}))
    assert alerts[0].severity == "red"
    assert "mañana a las 06:00" in alerts[0].message


def test_past_hours_are_ignored():
    assert evaluate_location(SANTIAGO, CURRENT_TIME, make_hourly(gust_kmh={5: 120})) == []


def test_hours_beyond_horizon_are_ignored():
    assert evaluate_location(SANTIAGO, CURRENT_TIME, make_hourly(gust_kmh={40: 120})) == []


def test_heavy_rain_levels():
    alerts = evaluate_location(SANTIAGO, CURRENT_TIME, make_hourly(precipitation_mm={12: 12.5}))
    assert kinds(alerts) == {"rain": "orange"}


def test_thunderstorm_takes_the_highest_severity_in_window():
    alerts = evaluate_location(SANTIAGO, CURRENT_TIME, make_hourly(weather_code={12: 95, 15: 99}))
    assert kinds(alerts) == {"storm": "red"}
    assert "granizo" in alerts[0].message


def test_frost_yellow_requires_high_humidity():
    dry = make_hourly(temperature_c={20: -1.0}, humidity_pct={20: 40})
    humid = make_hourly(temperature_c={20: -1.0}, humidity_pct={20: 85})
    assert evaluate_location(SANTIAGO, CURRENT_TIME, dry) == []
    assert kinds(evaluate_location(SANTIAGO, CURRENT_TIME, humid)) == {"frost": "yellow"}


def test_severe_frost_does_not_need_humidity():
    h = make_hourly(temperature_c={20: -4.0}, humidity_pct={20: 20})
    assert kinds(evaluate_location(SANTIAGO, CURRENT_TIME, h)) == {"frost": "orange"}


def test_extreme_heat_and_snow():
    h = make_hourly(temperature_c={13: 39.0}, weather_code={18: 75})
    assert kinds(evaluate_location(SANTIAGO, CURRENT_TIME, h)) == {"heat": "orange", "snow": "orange"}


def test_missing_values_are_skipped_without_crashing():
    h = make_hourly(gust_kmh={14: None}, temperature_c={14: None}, weather_code={14: None})
    assert evaluate_location(SANTIAGO, CURRENT_TIME, h) == []


def test_alerts_are_sorted_by_severity_and_max_severity_works():
    h = make_hourly(gust_kmh={14: 62}, precipitation_mm={14: 25})
    alerts = evaluate_location(SANTIAGO, CURRENT_TIME, h)
    assert [a.kind for a in alerts] == ["rain", "wind"]
    assert max_severity(alerts) == "red"
    assert max_severity([]) == "none"


# --- sismos -----------------------------------------------------------------
def quake(**kw):
    base = dict(id="q1", magnitude=6.2, place="45 km W of Valparaíso", time_ms=NOW_MS - 3_600_000,
                lat=-33.1, lon=-71.9, depth_km=35.0)
    base.update(kw)
    return Quake(**base)


def test_nearby_strong_quake_creates_alert_attached_to_nearest_location():
    alerts = evaluate_quakes([quake()], LOCATIONS, now_ms=NOW_MS)
    assert len(alerts) == 1
    a = alerts[0]
    assert (a.kind, a.severity, a.location_id) == ("earthquake", "orange", "valparaiso")
    assert a.title == "Sismo M6.2"


def test_quake_below_threshold_is_ignored():
    assert evaluate_quakes([quake(magnitude=4.9)], LOCATIONS, now_ms=NOW_MS) == []


def test_quake_far_from_any_location_is_ignored():
    far = quake(lat=-33.0, lon=-85.0)  # en pleno Pacífico
    assert evaluate_quakes([far], LOCATIONS, now_ms=NOW_MS) == []


def test_old_quake_is_ignored():
    old = quake(time_ms=NOW_MS - 72 * 3_600_000)
    assert evaluate_quakes([old], LOCATIONS, now_ms=NOW_MS) == []
