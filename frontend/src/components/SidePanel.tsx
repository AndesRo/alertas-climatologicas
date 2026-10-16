import { useMemo, useState } from "react";
import type { Alert, AlertKind, Severity, Status } from "../types";
import { KIND_LABEL, SEVERITY_META, SEVERITY_ORDER } from "../lib/severity";
import { clockFromEpoch, timeAgo } from "../lib/format";

export interface Layers {
  radar: boolean;
  quakes: boolean;
}

interface Props {
  alerts: Alert[] | null;
  status: Status | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  selectedKey: string | null;
  onSelectAlert: (alert: Alert) => void;
  layers: Layers;
  onToggleLayer: (layer: keyof Layers) => void;
  radarFailed: boolean;
  radarTime: number | null;
  className?: string;
}

function toggled<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

const SOURCES = [
  { label: "Open-Meteo", href: "https://open-meteo.com/" },
  { label: "USGS", href: "https://earthquake.usgs.gov/" },
  { label: "RainViewer", href: "https://www.rainviewer.com/" },
  { label: "OpenStreetMap", href: "https://www.openstreetmap.org/copyright" },
];

export function SidePanel({
  alerts,
  status,
  loading,
  error,
  onRetry,
  selectedKey,
  onSelectAlert,
  layers,
  onToggleLayer,
  radarFailed,
  radarTime,
  className = "",
}: Props) {
  const [severities, setSeverities] = useState<Set<Severity>>(new Set());
  const [kinds, setKinds] = useState<Set<AlertKind>>(new Set());

  const severityCounts = useMemo(() => {
    const counts: Record<Severity, number> = { red: 0, orange: 0, yellow: 0 };
    for (const a of alerts ?? []) counts[a.severity] += 1;
    return counts;
  }, [alerts]);

  const kindCounts = useMemo(() => {
    const counts = new Map<AlertKind, number>();
    for (const a of alerts ?? []) counts.set(a.kind, (counts.get(a.kind) ?? 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [alerts]);

  const visible = useMemo(
    () =>
      (alerts ?? []).filter(
        (a) => (severities.size === 0 || severities.has(a.severity)) && (kinds.size === 0 || kinds.has(a.kind)),
      ),
    [alerts, severities, kinds],
  );

  const hasFilters = severities.size > 0 || kinds.size > 0;
  const lastIngest = status?.last_ingest_at ?? null;
  const stale =
    !lastIngest || Date.now() - new Date(lastIngest).getTime() > (status?.interval_min ?? 15) * 3 * 60_000;
  const offline = error !== null;

  return (
    <aside
      aria-label="Alertas activas"
      className={`absolute z-[1100] flex flex-col overflow-hidden border border-line bg-trench/90 backdrop-blur-md max-lg:inset-x-0 max-lg:bottom-0 max-lg:max-h-[46dvh] max-lg:rounded-t-2xl lg:bottom-9 lg:left-4 lg:top-4 lg:w-[384px] lg:rounded-2xl ${className}`}
    >
      <header className="px-5 pb-4 pt-5">
        <h1 className="text-xl font-semibold tracking-tight">Alertas Climatologicas</h1>
        <p className="mt-0.5 text-sm text-fog">Clima y sismos en Chile, de Arica a Punta Arenas</p>
        <p className="mt-3 flex items-center gap-2 text-xs text-fog" role="status">
          <span
            aria-hidden
            className={`inline-block size-2 rounded-full ${offline || stale ? "bg-sev-yellow" : "bg-signal"}`}
          />
          {offline && !alerts
            ? "Sin conexión con el servidor"
            : lastIngest
              ? `Datos de ${timeAgo(lastIngest)}${offline ? ". Reconectando…" : ""}`
              : "Esperando la primera lectura"}
        </p>
        {status?.last_error && (
          <p className="mt-1 text-xs text-sev-yellow">
            Una fuente externa falló en la última lectura. Se muestran los datos anteriores.
          </p>
        )}
      </header>

      <div className="border-t border-line px-5 py-3">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Filtrar por severidad">
          {SEVERITY_ORDER.map((sev) => {
            const active = severities.has(sev);
            const { label, color } = SEVERITY_META[sev];
            return (
              <button
                key={sev}
                type="button"
                aria-pressed={active}
                onClick={() => setSeverities((s) => toggled(s, sev))}
                className="flex items-center gap-2 rounded-full border px-3 py-1 text-xs transition-colors hover:bg-white/5"
                style={{
                  borderColor: active ? color : "var(--color-line)",
                  background: active ? `${color}22` : undefined,
                }}
              >
                <span aria-hidden className="size-2 rounded-full" style={{ background: color }} />
                {label}
                <span className="font-mono text-fog">{severityCounts[sev]}</span>
              </button>
            );
          })}
        </div>
        {kindCounts.length > 1 && (
          <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label="Filtrar por tipo">
            {kindCounts.map(([kind, count]) => {
              const active = kinds.has(kind);
              return (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setKinds((k) => toggled(k, kind))}
                  className={`rounded-md px-2 py-0.5 text-xs transition-colors ${active ? "bg-signal/20 text-foam" : "text-fog hover:bg-white/5"
                    }`}
                >
                  {KIND_LABEL[kind]} <span className="font-mono">{count}</span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="slim-scroll min-h-0 flex-1 overflow-y-auto border-t border-line">
        {loading && !alerts && (
          <div className="px-5 py-6 text-sm text-fog">
            <p className="text-foam">Conectando con el servidor…</p>
            <p className="mt-1">En los planes gratuitos el primer acceso puede tardar hasta un minuto.</p>
          </div>
        )}

        {offline && !alerts && !loading && (
          <div className="px-5 py-6 text-sm">
            <p className="text-foam">No se pudo cargar la información.</p>
            <p className="mt-1 text-fog">{error}</p>
            <button
              type="button"
              onClick={onRetry}
              className="mt-3 rounded-md border border-line px-3 py-1.5 text-foam hover:bg-white/5"
            >
              Reintentar
            </button>
          </div>
        )}

        {alerts && alerts.length === 0 && (
          <div className="px-5 py-6 text-sm">
            <p className="text-foam">Sin alertas activas</p>
            <p className="mt-1 text-fog">
              Las condiciones previstas para las próximas 24 horas están bajo los umbrales en todas las ciudades.
            </p>
          </div>
        )}

        {alerts && alerts.length > 0 && visible.length === 0 && (
          <div className="px-5 py-6 text-sm">
            <p className="text-foam">Ninguna alerta coincide con los filtros.</p>
            {hasFilters && (
              <button
                type="button"
                onClick={() => {
                  setSeverities(new Set());
                  setKinds(new Set());
                }}
                className="mt-3 rounded-md border border-line px-3 py-1.5 text-foam hover:bg-white/5"
              >
                Quitar filtros
              </button>
            )}
          </div>
        )}

        <ul>
          {visible.map((alert) => {
            const { color, label } = SEVERITY_META[alert.severity];
            const selected = alert.key === selectedKey;
            return (
              <li key={alert.key} className="border-b border-line/60 last:border-b-0">
                <button
                  type="button"
                  onClick={() => onSelectAlert(alert)}
                  aria-current={selected}
                  className={`flex w-full gap-3 py-3 pl-4 pr-5 text-left transition-colors hover:bg-white/5 ${selected ? "bg-white/5" : ""
                    }`}
                >
                  <span aria-hidden className="mt-0.5 w-1 shrink-0 self-stretch rounded-full" style={{ background: color }} />
                  <span className="min-w-0">
                    <span className="flex items-baseline gap-2">
                      <span className="font-medium">{alert.title}</span>
                      <span className="text-xs text-fog">{alert.location_name}</span>
                    </span>
                    <span className="mt-0.5 block text-sm leading-snug text-fog">{alert.message}</span>
                    <span className="sr-only">Severidad {label}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>

      <div className="space-y-2 border-t border-line px-5 py-3 text-sm">
        <label className="flex cursor-pointer items-center justify-between gap-3">
          <span>
            Radar de lluvia
            <span className="ml-2 text-xs text-fog">
              {radarFailed ? "no disponible" : radarTime ? `a las ${clockFromEpoch(radarTime)}` : ""}
            </span>
          </span>
          <input
            type="checkbox"
            className="size-4 accent-signal"
            checked={layers.radar}
            disabled={radarFailed}
            onChange={() => onToggleLayer("radar")}
          />
        </label>
        <label className="flex cursor-pointer items-center justify-between gap-3">
          <span>
            Sismos de los últimos 7 días
            <span className="ml-2 text-xs text-fog">M4.5 o más</span>
          </span>
          <input
            type="checkbox"
            className="size-4 accent-signal"
            checked={layers.quakes}
            onChange={() => onToggleLayer("quakes")}
          />
        </label>
      </div>

      <footer className="border-t border-line px-5 py-3 text-[11px] leading-relaxed text-fog">
        <p>
          created by Andres(@AndesRo)
        </p>
        <p className="mt-1.5">
          Datos:{" "}
          {SOURCES.map((s, i) => (
            <span key={s.label}>
              <a href={s.href} target="_blank" rel="noreferrer" className="underline decoration-line underline-offset-2 hover:text-foam">
                {s.label}
              </a>
              {i < SOURCES.length - 1 ? ", " : "."}
            </span>
          ))}
        </p>
      </footer>
    </aside>
  );
}