import type { Alert, Forecast, LocationSummary, PrecipGrid, Quake, Rules, Status } from "./types";

// Vacío en desarrollo (proxy de Vite). En producción: URL del backend sin barra final.
const BASE = ((import.meta.env.VITE_API_URL as string | undefined) ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { signal });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError("No se pudo conectar con el servidor.");
  }

  if (!response.ok) {
    let detail = `El servidor respondió con error ${response.status}.`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // la respuesta no tenía cuerpo JSON
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  status: () => get<Status>("/api/status"),
  rules: () => get<Rules>("/api/rules"),
  locations: () => get<LocationSummary[]>("/api/locations"),
  alerts: () => get<Alert[]>("/api/alerts"),
  quakes: () => get<Quake[]>("/api/quakes"),
  precip: () => get<PrecipGrid>("/api/precip"),
  forecast: (id: string, signal?: AbortSignal) => get<Forecast>(`/api/forecast/${id}`, signal),
};