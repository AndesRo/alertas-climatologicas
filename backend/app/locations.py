"""Puntos de monitoreo: ciudades de norte a sur de Chile continental."""

from __future__ import annotations

from .models import Location

LOCATIONS: list[Location] = [
    Location(id="arica", name="Arica", region="Arica y Parinacota", lat=-18.4783, lon=-70.3126),
    Location(id="iquique", name="Iquique", region="Tarapacá", lat=-20.2307, lon=-70.1357),
    Location(id="calama", name="Calama", region="Antofagasta", lat=-22.4540, lon=-68.9292),
    Location(id="antofagasta", name="Antofagasta", region="Antofagasta", lat=-23.6509, lon=-70.3975),
    Location(id="copiapo", name="Copiapó", region="Atacama", lat=-27.3668, lon=-70.3323),
    Location(id="la-serena", name="La Serena", region="Coquimbo", lat=-29.9027, lon=-71.2519),
    Location(id="valparaiso", name="Valparaíso", region="Valparaíso", lat=-33.0472, lon=-71.6127),
    Location(id="santiago", name="Santiago", region="Metropolitana", lat=-33.4489, lon=-70.6693),
    Location(id="rancagua", name="Rancagua", region="O'Higgins", lat=-34.1708, lon=-70.7444),
    Location(id="talca", name="Talca", region="Maule", lat=-35.4264, lon=-71.6554),
    Location(id="chillan", name="Chillán", region="Ñuble", lat=-36.6063, lon=-72.1034),
    Location(id="concepcion", name="Concepción", region="Biobío", lat=-36.8201, lon=-73.0444),
    Location(id="temuco", name="Temuco", region="La Araucanía", lat=-38.7359, lon=-72.5904),
    Location(id="villarrica", name="Villarrica", region="La Araucanía", lat=-39.2857, lon=-72.2279),
    Location(id="valdivia", name="Valdivia", region="Los Ríos", lat=-39.8196, lon=-73.2452),
    Location(id="osorno", name="Osorno", region="Los Lagos", lat=-40.5739, lon=-73.1317),
    Location(id="puerto-montt", name="Puerto Montt", region="Los Lagos", lat=-41.4693, lon=-72.9424),
    Location(id="coyhaique", name="Coyhaique", region="Aysén", lat=-45.5712, lon=-72.0685),
    Location(id="punta-arenas", name="Punta Arenas", region="Magallanes", lat=-53.1638, lon=-70.9171),
]

LOCATIONS_BY_ID: dict[str, Location] = {loc.id: loc for loc in LOCATIONS}
