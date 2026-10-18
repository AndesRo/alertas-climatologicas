import type { PrecipGrid } from "../types";

export interface PrecipBin {
  /** Intensidad mínima (mm/h) de este tramo. */
  min: number;
  color: string;
  opacity: number;
  label: string;
}

// Rampa que sube en luminosidad (azul oscuro a blanco): se lee bien sobre el mapa oscuro y no se
// confunde con los colores de severidad (amarillo, naranja, rojo) ni con los sismos (violeta).
// Los tramos bajos son los más comunes (lluvia débil) y los que más se pierden sobre el mapa oscuro,
// por eso arrancan en un azul claro y bastante opaco.
export const PRECIP_BINS: PrecipBin[] = [
  { min: 0.1, color: "#3b86d1", opacity: 0.65, label: "0,1" },
  { min: 0.5, color: "#4aa8ee", opacity: 0.75, label: "0,5" },
  { min: 1, color: "#5ad1f5", opacity: 0.82, label: "1" },
  { min: 2.5, color: "#b6f3ff", opacity: 0.88, label: "2,5" },
  { min: 5, color: "#ffffff", opacity: 0.94, label: "5+" },
];

/** Tramo de la escala que corresponde a `mm`, o null si no llueve lo suficiente como para dibujarse. */
export function precipBin(mm: number | null | undefined): PrecipBin | null {
  if (mm == null || mm < PRECIP_BINS[0].min) return null;
  let bin = PRECIP_BINS[0];
  for (const candidate of PRECIP_BINS) if (mm >= candidate.min) bin = candidate;
  return bin;
}

/** Cuántas celdas tienen lluvia suficiente para dibujarse en la hora `index` de la grilla. */
export function rainyCellCount(grid: PrecipGrid, index: number): number {
  let count = 0;
  for (const cell of grid.cells) if (precipBin(cell.mm[index])) count += 1;
  return count;
}

/** Primera hora entre `from` y `to` (ambas inclusive) con lluvia en alguna celda, o null si no hay ninguna. */
export function nextRainIndex(grid: PrecipGrid, from: number, to: number): number | null {
  const last = Math.min(to, grid.times.length - 1);
  for (let i = Math.max(from, 0); i <= last; i += 1) if (rainyCellCount(grid, i) > 0) return i;
  return null;
}

const MAX_OFFSET_HOURS = 23;
const HOUR_MS = 3_600_000;

/** "2026-10-17T03:00" (UTC, sin Z) a milisegundos desde la época. */
function utcMs(time: string): number {
  return Date.parse(`${time}:00Z`);
}

export interface PrecipPlan {
  /** Índice de la hora en curso dentro de `grid.times`. */
  start: number;
  /** Cuántas horas hacia adelante se puede mover el control. */
  max: number;
}

/**
 * Cada valor es la lluvia de la hora que *termina* en `times[i]`. La hora en curso es, por lo tanto,
 * la primera que termina en el futuro. La grilla se actualiza una vez por hora, así que puede llevar
 * hasta ~1 h de antigüedad: calcular esto con el reloj de hoy evita mostrar una hora ya pasada como "ahora".
 */
export function planPrecip(grid: PrecipGrid | null, now: number = Date.now()): PrecipPlan | null {
  if (!grid || grid.times.length === 0) return null;
  const start = grid.times.findIndex((t) => utcMs(t) > now);
  if (start < 0) return null;
  return { start, max: Math.min(grid.times.length - 1 - start, MAX_OFFSET_HOURS) };
}

const TIME_ZONE = "America/Santiago";
const weekday = new Intl.DateTimeFormat("es-CL", { weekday: "short", timeZone: TIME_ZONE });
const clock = new Intl.DateTimeFormat("es-CL", {
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: TIME_ZONE,
});

/** "sáb 15:00 – 16:00": la hora que cubre `grid.times[index]`, en hora de Chile. */
export function precipPeriodLabel(grid: PrecipGrid, index: number): string {
  const end = utcMs(grid.times[index]);
  const begin = end - HOUR_MS;
  return `${weekday.format(begin).replace(".", "")} ${clock.format(begin)} – ${clock.format(end)}`;
}