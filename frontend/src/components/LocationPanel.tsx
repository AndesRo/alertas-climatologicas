import { Suspense, lazy, useEffect, useState } from "react";
import { api } from "../api";
import type { Forecast, LocationSummary, Rules } from "../types";
import { fmt, timeAgo } from "../lib/format";
import { SEVERITY_META, weatherLabel } from "../lib/severity";

// Recharts pesa bastante: se descarga solo cuando se abre el detalle de una ciudad.
const ForecastChart = lazy(() => import("./ForecastChart").then((m) => ({ default: m.ForecastChart })));

type State = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: Forecast };

interface Props {
  locationId: string;
  summary: LocationSummary | undefined;
  rules: Rules | null;
  onClose: () => void;
  className?: string;
}

function Reading({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-fog">{label}</dt>
      <dd className="mt-0.5 font-mono text-lg">{value}</dd>
    </div>
  );
}

// Se monta con `key={locationId}`, así cada ciudad arranca desde "loading" sin efectos extra.
export function LocationPanel({ locationId, summary, rules, onClose, className = "" }: Props) {
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api
      .forecast(locationId, controller.signal)
      .then((data) => setState({ status: "ready", data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: error instanceof Error ? error.message : "Error desconocido" });
      });
    return () => controller.abort();
  }, [locationId, attempt]);

  const forecast = state.status === "ready" ? state.data : null;
  const current = forecast?.current ?? summary?.current ?? null;

  return (
    <section
      aria-label={`Detalle de ${summary?.name ?? "la ciudad"}`}
      className={`absolute z-[1100] flex flex-col overflow-hidden border border-line bg-trench/95 backdrop-blur-md max-lg:inset-x-0 max-lg:bottom-0 max-lg:top-16 max-lg:rounded-t-2xl lg:bottom-9 lg:right-4 lg:top-4 lg:w-[420px] lg:rounded-2xl ${className}`}
    >
      <header className="flex items-start justify-between gap-3 px-5 pb-4 pt-5">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">{summary?.name ?? "Ciudad"}</h2>
          <p className="text-sm text-fog">{summary?.region}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar detalle"
          className="rounded-md p-1.5 text-fog hover:bg-white/5 hover:text-foam"
        >
          <svg viewBox="0 0 20 20" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M5 5l10 10M15 5L5 15" />
          </svg>
        </button>
      </header>

      <div className="slim-scroll min-h-0 flex-1 overflow-y-auto">
        <div className="border-t border-line px-5 py-4">
          <p className="mb-3 text-sm text-fog">{weatherLabel(current?.weather_code)}</p>
          <dl className="grid grid-cols-3 gap-x-4 gap-y-3">
            <Reading label="Temperatura" value={fmt(current?.temperature_c, "°C", 1)} />
            <Reading label="Humedad" value={fmt(current?.humidity_pct, "%")} />
            <Reading label="Lluvia" value={fmt(current?.precipitation_mm, "mm", 1)} />
            <Reading label="Viento" value={fmt(current?.wind_kmh, "km/h")} />
            <Reading label="Ráfagas" value={fmt(current?.gust_kmh, "km/h")} />
          </dl>
        </div>

        <div className="border-t border-line">
          <h3 className="px-5 pb-1 pt-4 text-sm font-medium">Alertas para las próximas 24 horas</h3>
          {state.status === "loading" && <p className="px-5 pb-4 text-sm text-fog">Cargando…</p>}
          {state.status === "error" && (
            <div className="px-5 pb-4 text-sm">
              <p className="text-fog">{state.message}</p>
              <button
                type="button"
                onClick={() => {
                  setState({ status: "loading" });
                  setAttempt((n) => n + 1);
                }}
                className="mt-2 rounded-md border border-line px-3 py-1.5 text-foam hover:bg-white/5"
              >
                Reintentar
              </button>
            </div>
          )}
          {forecast && forecast.alerts.length === 0 && (
            <p className="px-5 pb-4 text-sm text-fog">Sin alertas. Todo bajo los umbrales.</p>
          )}
          {forecast && forecast.alerts.length > 0 && (
            <ul className="pb-2">
              {forecast.alerts.map((a) => (
                <li key={a.key} className="flex gap-3 py-2 pl-4 pr-5">
                  <span aria-hidden className="w-1 shrink-0 self-stretch rounded-full" style={{ background: SEVERITY_META[a.severity].color }} />
                  <span>
                    <span className="block font-medium">{a.title}</span>
                    <span className="block text-sm leading-snug text-fog">{a.message}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {forecast && (
          <div className="border-t border-line px-5 py-4">
            <h3 className="mb-3 text-sm font-medium">Pronóstico por hora</h3>
            <Suspense fallback={<p className="h-[236px] text-sm text-fog">Cargando gráfico…</p>}>
              <ForecastChart hourly={forecast.hourly} currentTime={forecast.current.time} rules={rules} />
            </Suspense>
            <p className="mt-3 text-xs text-fog">Pronóstico obtenido {timeAgo(forecast.fetched_at)}.</p>
          </div>
        )}
      </div>
    </section>
  );
}
