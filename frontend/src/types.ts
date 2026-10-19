// Espejo de los modelos Pydantic del backend (backend/app/models.py).

export type Severity = "yellow" | "orange" | "red";
export type SeverityOrNone = Severity | "none";
export type AlertKind = "wind" | "rain" | "storm" | "frost" | "heat" | "snow" | "earthquake";

export interface Location {
  id: string;
  name: string;
  region: string;
  lat: number;
  lon: number;
}

export interface Current {
  time: string;
  temperature_c: number | null;
  humidity_pct: number | null;
  precipitation_mm: number | null;
  wind_kmh: number | null;
  gust_kmh: number | null;
  weather_code: number | null;
}

export interface Hourly {
  time: string[];
  temperature_c: (number | null)[];
  humidity_pct: (number | null)[];
  precipitation_mm: (number | null)[];
  wind_kmh: (number | null)[];
  gust_kmh: (number | null)[];
  weather_code: (number | null)[];
}

export interface LocationSummary extends Location {
  current: Current | null;
  severity: SeverityOrNone;
  alert_count: number;
}

export interface Alert {
  key: string;
  kind: AlertKind;
  severity: Severity;
  title: string;
  message: string;
  location_id: string | null;
  location_name: string | null;
  lat: number;
  lon: number;
  value: number;
  unit: string;
  at: string | null;
}

export interface Quake {
  id: string;
  magnitude: number;
  place: string;
  time_ms: number;
  lat: number;
  lon: number;
  depth_km: number | null;
  url: string | null;
}

export interface Forecast {
  location: Location;
  fetched_at: string;
  current: Current;
  hourly: Hourly;
  alerts: Alert[];
}

export interface Status {
  last_ingest_at: string | null;
  last_error: string | null;
  locations: number;
  alerts: number;
  quakes: number;
  interval_min: number;
}

/** Celda de la grilla de precipitación: `mm[i]` es la lluvia (mm) de la hora que termina en `times[i]`. */
export interface PrecipCell {
  lat: number;
  lon: number;
  mm: (number | null)[];
}

/** Respuesta de GET /api/precip: precipitación prevista por el modelo de Open-Meteo (no es una medición). */
export interface PrecipGrid {
  fetched_at: string;
  /** Lado de cada celda en grados; la celda queda centrada en (lat, lon). */
  step_deg: number;
  /** Horas en UTC, sin sufijo Z. */
  times: string[];
  cells: PrecipCell[];
  demo: boolean;
}

export interface Thresholds {
  yellow: number;
  orange: number;
  red: number;
}

export interface Rules {
  wind_gust_kmh: Thresholds;
  rain_mm_h: Thresholds;
  heat_c: Thresholds;
  frost_c: Thresholds;
  quake_magnitude: Thresholds;
  quake_radius_km: number;
  horizon_hours: number;
}