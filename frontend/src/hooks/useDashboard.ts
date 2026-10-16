import { useCallback } from "react";
import { api } from "../api";
import type { Alert, LocationSummary, Quake, Status } from "../types";
import { usePolling } from "./usePolling";

export interface DashboardData {
  status: Status;
  locations: LocationSummary[];
  alerts: Alert[];
  quakes: Quake[];
}

/** Una sola ronda de peticiones en paralelo, refrescada cada minuto. */
export function useDashboard() {
  const fetchAll = useCallback(async (): Promise<DashboardData> => {
    const [status, locations, alerts, quakes] = await Promise.all([
      api.status(),
      api.locations(),
      api.alerts(),
      api.quakes(),
    ]);
    return { status, locations, alerts, quakes };
  }, []);

  return usePolling(fetchAll, 60_000);
}
