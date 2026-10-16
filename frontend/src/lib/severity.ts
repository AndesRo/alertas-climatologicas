import type { AlertKind, Severity, SeverityOrNone } from "../types";

export const SEVERITY_RANK: Record<SeverityOrNone, number> = {
  none: 0,
  yellow: 1,
  orange: 2,
  red: 3,
};

export const SEVERITY_ORDER: Severity[] = ["red", "orange", "yellow"];

export const SEVERITY_META: Record<Severity, { label: string; color: string }> = {
  yellow: { label: "Amarilla", color: "#f5c451" },
  orange: { label: "Naranja", color: "#ff8a3d" },
  red: { label: "Roja", color: "#ff4d5e" },
};

export const QUAKE_COLOR = "#b28dff";

export const KIND_LABEL: Record<AlertKind, string> = {
  wind: "Viento",
  rain: "Lluvia",
  storm: "Tormenta",
  frost: "Helada",
  heat: "Calor",
  snow: "Nieve",
  earthquake: "Sismo",
};

// Códigos WMO usados por Open-Meteo.
const WEATHER_LABEL: Record<number, string> = {
  0: "Despejado",
  1: "Mayormente despejado",
  2: "Parcialmente nublado",
  3: "Nublado",
  45: "Niebla",
  48: "Niebla con escarcha",
  51: "Llovizna débil",
  53: "Llovizna",
  55: "Llovizna intensa",
  56: "Llovizna helada",
  57: "Llovizna helada intensa",
  61: "Lluvia débil",
  63: "Lluvia moderada",
  65: "Lluvia fuerte",
  66: "Lluvia helada",
  67: "Lluvia helada fuerte",
  71: "Nieve débil",
  73: "Nieve moderada",
  75: "Nieve fuerte",
  77: "Granos de nieve",
  80: "Chubascos débiles",
  81: "Chubascos moderados",
  82: "Chubascos violentos",
  85: "Chubascos de nieve",
  86: "Chubascos de nieve intensos",
  95: "Tormenta eléctrica",
  96: "Tormenta con granizo",
  99: "Tormenta con granizo fuerte",
};

export function weatherLabel(code: number | null | undefined): string {
  if (code == null) return "Sin datos";
  return WEATHER_LABEL[code] ?? `Código ${code}`;
}
