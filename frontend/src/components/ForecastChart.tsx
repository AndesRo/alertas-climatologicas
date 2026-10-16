import { useMemo, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Hourly, Rules, Thresholds } from "../types";
import { dayHourLabel, hourLabel } from "../lib/format";
import { SEVERITY_META } from "../lib/severity";

type Metric = "wind" | "rain" | "temp";

const TABS: { id: Metric; label: string; unit: string }[] = [
  { id: "wind", label: "Viento", unit: "km/h" },
  { id: "rain", label: "Lluvia", unit: "mm/h" },
  { id: "temp", label: "Temperatura", unit: "°C" },
];

const GRID = "#1e2e3d";
const TICK = { fill: "#9db0c1", fontSize: 11 };
const WIND = "#4cc9f0";
const GUST = "#e8f0f6";

interface Line {
  y: number;
  color: string;
}

function linesFrom(th: Thresholds): Line[] {
  return [
    { y: th.yellow, color: SEVERITY_META.yellow.color },
    { y: th.orange, color: SEVERITY_META.orange.color },
    { y: th.red, color: SEVERITY_META.red.color },
  ];
}

function thresholdLines(metric: Metric, rules: Rules | null): Line[] {
  if (!rules) return [];
  if (metric === "wind") return linesFrom(rules.wind_gust_kmh);
  if (metric === "rain") return linesFrom(rules.rain_mm_h);
  return [...linesFrom(rules.heat_c), ...linesFrom(rules.frost_c)];
}

interface Props {
  hourly: Hourly;
  currentTime: string;
  rules: Rules | null;
}

export function ForecastChart({ hourly, currentTime, rules }: Props) {
  const [metric, setMetric] = useState<Metric>("wind");
  const tab = TABS.find((t) => t.id === metric)!;

  const rows = useMemo(
    () =>
      hourly.time.map((time, i) => ({
        time,
        wind: hourly.wind_kmh[i],
        gust: hourly.gust_kmh[i],
        rain: hourly.precipitation_mm[i],
        temp: hourly.temperature_c[i],
      })),
    [hourly],
  );

  const nowKey = currentTime.slice(0, 13) + ":00";
  const lines = thresholdLines(metric, rules);

  return (
    <div>
      <div role="tablist" aria-label="Variable del pronóstico" className="mb-3 flex gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={metric === t.id}
            onClick={() => setMetric(t.id)}
            className={`rounded-md px-3 py-1 text-xs transition-colors ${
              metric === t.id ? "bg-signal/20 text-foam" : "text-fog hover:bg-white/5"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="img" aria-label={`Pronóstico horario de ${tab.label.toLowerCase()} para las próximas horas`}>
        <ResponsiveContainer width="100%" height={200}>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -14 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="time" tickFormatter={hourLabel} interval={5} tick={TICK} stroke={GRID} />
            {metric === "wind" && (
              <YAxis tick={TICK} stroke={GRID} domain={[0, (max: number) => Math.max(40, Math.ceil((max + 5) / 10) * 10)]} />
            )}
            {metric === "rain" && (
              <YAxis tick={TICK} stroke={GRID} domain={[0, (max: number) => Math.max(2, Math.ceil(max + 1))]} />
            )}
            {metric === "temp" && (
              <YAxis
                tick={TICK}
                stroke={GRID}
                domain={[(min: number) => Math.floor(min) - 2, (max: number) => Math.ceil(max) + 2]}
              />
            )}
            <Tooltip
              contentStyle={{ background: "#101b26", border: "1px solid #1e2e3d", borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: "#9db0c1" }}
              labelFormatter={(label) => dayHourLabel(String(label), currentTime)}
              formatter={(value, name) => [`${Number(value).toFixed(1)} ${tab.unit}`, String(name)]}
            />
            {lines.map((l) => (
              <ReferenceLine key={`${metric}-${l.y}`} y={l.y} stroke={l.color} strokeDasharray="4 4" strokeOpacity={0.7} ifOverflow="hidden" />
            ))}
            <ReferenceLine x={nowKey} stroke="#e8f0f6" strokeDasharray="2 3" strokeOpacity={0.6} />
            {metric === "wind" && <Line type="monotone" dataKey="wind" name="Viento" stroke={WIND} strokeWidth={2} dot={false} />}
            {metric === "wind" && <Line type="monotone" dataKey="gust" name="Ráfagas" stroke={GUST} strokeWidth={1.5} dot={false} />}
            {metric === "rain" && <Bar dataKey="rain" name="Precipitación" fill={WIND} fillOpacity={0.8} />}
            {metric === "temp" && <Line type="monotone" dataKey="temp" name="Temperatura" stroke={WIND} strokeWidth={2} dot={false} />}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-xs text-fog">La línea punteada vertical marca la hora actual. Las horizontales, los umbrales de alerta.</p>
    </div>
  );
}
