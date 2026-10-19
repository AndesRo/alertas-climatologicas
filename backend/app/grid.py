"""Grilla de puntos sobre Chile para la capa de precipitación prevista.

Chile es una franja angosta (100 a 400 km de ancho) y muy larga, así que una grilla
rectangular sobre su caja envolvente desperdiciaría casi todos los puntos en el océano y en
Argentina. En vez de eso se define, cada 2 grados de latitud, el ancho de la franja (costa y
mar adyacente hasta la frontera) y se interpola entre esos anclajes.

Los puntos caen en grados enteros: así las celdas de 1° x 1° de filas vecinas quedan alineadas
y el mapa se ve como una grilla, no como una escalera.
"""

from __future__ import annotations

import math

GRID_STEP_DEG = 1.0

# (latitud, longitud oeste, longitud este). Incluye ~0,5° de mar para ver sistemas que llegan a la costa.
ENVELOPE: list[tuple[float, float, float]] = [
    (-18, -71.0, -68.5),
    (-20, -71.0, -68.0),
    (-22, -71.0, -67.5),
    (-24, -71.0, -67.0),
    (-26, -71.5, -68.0),
    (-28, -71.8, -68.5),
    (-30, -72.0, -69.5),
    (-32, -72.2, -69.8),
    (-34, -72.5, -69.8),
    (-36, -73.5, -70.5),
    (-38, -73.8, -71.0),
    (-40, -74.0, -71.2),
    (-42, -74.2, -71.5),
    (-44, -74.5, -71.5),
    (-46, -75.0, -71.5),
    (-48, -75.5, -72.0),
    (-50, -75.5, -72.0),
    (-52, -75.0, -69.0),
    (-54, -73.5, -67.0),
    (-56, -72.0, -66.0),
]

NORTH_LAT = -18
SOUTH_LAT = -55


def _bounds_at(lat: float) -> tuple[float, float]:
    """Interpola linealmente (oeste, este) entre los dos anclajes que rodean `lat`."""
    for (lat_a, w_a, e_a), (lat_b, w_b, e_b) in zip(ENVELOPE, ENVELOPE[1:]):
        if lat_a >= lat >= lat_b:
            t = (lat_a - lat) / (lat_a - lat_b)
            return w_a + t * (w_b - w_a), e_a + t * (e_b - e_a)
    raise ValueError(f"Latitud fuera del rango de la grilla: {lat}")


def build_grid(step: float = GRID_STEP_DEG) -> list[tuple[float, float]]:
    """Devuelve los puntos (lat, lon) de la grilla, de norte a sur y de oeste a este."""
    points: list[tuple[float, float]] = []
    lat = float(NORTH_LAT)
    while lat >= SOUTH_LAT - 1e-9:
        west, east = _bounds_at(lat)
        lon = math.floor(west / step) * step
        while lon <= math.ceil(east / step) * step + 1e-9:
            points.append((round(lat, 2), round(lon, 2)))
            lon += step
        lat -= step
    return points


GRID_POINTS: list[tuple[float, float]] = build_grid()