import { useEffect } from "react";
import L from "leaflet";
import { CircleMarker, MapContainer, Marker, TileLayer, Tooltip, ZoomControl, useMap } from "react-leaflet";
import type { LocationSummary, PrecipGrid, Quake, SeverityOrNone } from "../types";
import { QUAKE_COLOR } from "../lib/severity";
import { fmt, timeAgo } from "../lib/format";
import { PrecipLayer } from "./PrecipLayer";

// Chile continental, de Arica a Punta Arenas.
const CHILE_BOUNDS: L.LatLngBoundsExpression = [
  [-56, -78],
  [-17, -64],
];

// Mapa base. Por defecto: teselas estándar de OpenStreetMap (gratis, sin clave), oscurecidas con un filtro CSS.
// CARTO ahora exige clave API y mostraba la marca "API KEY REQUIRED" sobre todo el mapa.
// Para usar otro proveedor (MapTiler, Stadia, Jawg...) define VITE_TILE_URL y VITE_TILE_ATTRIBUTION;
// en ese caso no se aplica el filtro, porque se asume que el estilo elegido ya es el que quieres.
const CUSTOM_TILE_URL = import.meta.env.VITE_TILE_URL as string | undefined;
const TILE_URL = CUSTOM_TILE_URL || "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  (import.meta.env.VITE_TILE_ATTRIBUTION as string | undefined) ||
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

const iconCache = new Map<string, L.DivIcon>();

function pinIcon(severity: SeverityOrNone, selected: boolean): L.DivIcon {
  const key = `${severity}-${selected}`;
  let icon = iconCache.get(key);
  if (!icon) {
    icon = L.divIcon({
      className: "pin-wrap",
      html: `<span class="pin pin-${severity}${selected ? " pin-selected" : ""}"></span>`,
      iconSize: [22, 22],
      iconAnchor: [11, 11],
    });
    iconCache.set(key, icon);
  }
  return icon;
}

function Focus({ target }: { target: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (!target) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    map.flyTo(target, Math.max(map.getZoom(), 7), { animate: !reduceMotion, duration: 0.8 });
  }, [map, target]);
  return null;
}

interface Props {
  locations: LocationSummary[];
  quakes: Quake[];
  showQuakes: boolean;
  radarUrl: string | null;
  /** Grilla de precipitación y la hora a dibujar; null en cualquiera de los dos apaga la capa. */
  precip: PrecipGrid | null;
  precipIndex: number | null;
  selectedId: string | null;
  focus: [number, number] | null;
  onSelectLocation: (id: string) => void;
}

export function MapView({
  locations,
  quakes,
  showQuakes,
  radarUrl,
  precip,
  precipIndex,
  selectedId,
  focus,
  onSelectLocation,
}: Props) {
  return (
    <MapContainer
      bounds={CHILE_BOUNDS}
      boundsOptions={{ padding: [20, 20] }}
      zoomSnap={0.5}
      minZoom={3}
      maxZoom={12}
      zoomControl={false}
      className="absolute inset-0 h-full w-full"
    >
      <TileLayer
        url={TILE_URL}
        maxZoom={19}
        className={CUSTOM_TILE_URL ? undefined : "basemap-dark"}
        attribution={TILE_ATTRIBUTION}
      />

      {radarUrl && <TileLayer key={radarUrl} url={radarUrl} opacity={0.7} maxNativeZoom={7} maxZoom={12} zIndex={5} />}

      {precip && precipIndex !== null && <PrecipLayer grid={precip} index={precipIndex} />}

      {showQuakes &&
        quakes.map((q) => {
          const recent = Date.now() - q.time_ms < 24 * 3_600_000;
          return (
            <CircleMarker
              key={q.id}
              center={[q.lat, q.lon]}
              radius={Math.max(4, (q.magnitude - 3.5) * 4)}
              pathOptions={{
                color: QUAKE_COLOR,
                weight: recent ? 2 : 1,
                fillColor: QUAKE_COLOR,
                fillOpacity: recent ? 0.35 : 0.12,
              }}
            >
              <Tooltip direction="top">
                <strong>Sismo M{q.magnitude.toFixed(1)}</strong>
                <br />
                {q.place}
                <br />
                {timeAgo(new Date(q.time_ms).toISOString())}, a {fmt(q.depth_km, "km")} de profundidad
              </Tooltip>
            </CircleMarker>
          );
        })}

      {locations.map((loc) => (
        <Marker
          key={loc.id}
          position={[loc.lat, loc.lon]}
          icon={pinIcon(loc.severity, loc.id === selectedId)}
          title={loc.name}
          alt={loc.name}
          eventHandlers={{ click: () => onSelectLocation(loc.id) }}
        >
          <Tooltip direction="top" offset={[0, -10]}>
            <strong>{loc.name}</strong>
            {loc.current?.temperature_c != null && <span> {fmt(loc.current.temperature_c, "°C")}</span>}
          </Tooltip>
        </Marker>
      ))}

      <ZoomControl position="bottomright" />
      <Focus target={focus} />
    </MapContainer>
  );
}