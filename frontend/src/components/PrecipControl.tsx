import { useMemo } from "react";
import type { PrecipGrid } from "../types";
import { PRECIP_BINS, nextRainIndex, precipPeriodLabel, rainyCellCount, type PrecipPlan } from "../lib/precip";
import { timeAgo } from "../lib/format";

interface Props {
  grid: PrecipGrid;
  plan: PrecipPlan;
  offset: number;
  onOffset: (offset: number) => void;
  className?: string;
}

/** Tarjeta sobre el mapa: hora de la precipitación mostrada, control para moverla y leyenda de colores. */
export function PrecipControl({ grid, plan, offset, onOffset, className = "" }: Props) {
  const index = plan.start + offset;
  const period = precipPeriodLabel(grid, index);
  const when = offset === 0 ? "Ahora" : `En ${offset} h`;

  const rainy = useMemo(() => rainyCellCount(grid, index), [grid, index]);
  // Solo se busca otra hora cuando esta está seca: así un mapa vacío se explica a sí mismo.
  const next = useMemo(
    () => (rainy === 0 ? nextRainIndex(grid, index + 1, plan.start + plan.max) : null),
    [grid, index, plan, rainy],
  );

  return (
    <section
      aria-label="Precipitación prevista"
      className={`absolute z-[1050] rounded-xl border border-line bg-trench/90 px-4 py-3 backdrop-blur-md max-lg:inset-x-3 max-lg:top-3 lg:bottom-9 lg:left-[416px] lg:w-[400px] ${className}`}
    >
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium">{when}</span>
        <span className="text-xs text-fog">{period}</span>
      </div>

      <input
        type="range"
        min={0}
        max={plan.max}
        step={1}
        value={offset}
        onChange={(event) => onOffset(Number(event.target.value))}
        aria-label="Hora de la precipitación prevista"
        aria-valuetext={`${when}, ${period}`}
        className="mt-2 block w-full accent-signal"
      />

      <div role="status" className="mt-2 text-sm">
        {rainy > 0 ? (
          <p>
            Lluvia prevista en {rainy} de {grid.cells.length} zonas.
          </p>
        ) : next !== null ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p>Sin lluvia prevista en esta hora.</p>
            <button
              type="button"
              onClick={() => onOffset(next - plan.start)}
              className="rounded-md border border-line px-2.5 py-1 text-xs text-foam hover:bg-white/5"
            >
              Ver la próxima lluvia ({precipPeriodLabel(grid, next)})
            </button>
          </div>
        ) : (
          <p>El modelo no prevé lluvia en Chile en las próximas {plan.max} horas.</p>
        )}
      </div>

      <ul aria-label="Escala de precipitación en milímetros por hora" className="mt-2 flex items-center gap-1 text-[11px] text-fog">
        {PRECIP_BINS.map((bin) => (
          <li key={bin.label} className="flex items-center gap-1">
            <span
              aria-hidden
              className="inline-block h-2.5 w-5 rounded-sm"
              style={{ background: bin.color, opacity: Math.min(1, bin.opacity + 0.15) }}
            />
            <span className="mr-1.5">{bin.label}</span>
          </li>
        ))}
        <li>mm/h</li>
      </ul>

      <p className="mt-2 text-[11px] leading-snug text-fog">
        Pronóstico del modelo de Open-Meteo, no una medición. Actualizado {timeAgo(grid.fetched_at)}.
        {grid.demo ? " Datos de demostración." : ""}
      </p>
    </section>
  );
}