import { useMemo } from "react";
import { Pane, Rectangle } from "react-leaflet";
import type { PrecipGrid } from "../types";
import { precipBin } from "../lib/precip";

type Bounds = [[number, number], [number, number]];

interface Props {
  grid: PrecipGrid;
  /** Índice de la hora a mostrar dentro de `grid.times`. */
  index: number;
}

/**
 * Celdas de precipitación prevista. Van en un panel propio entre los mapas base y los sismos
 * (z-index 300), así que no tapan marcadores ni tooltips. El desenfoque que funde las celdas
 * de 1° en manchas continuas lo aplica el CSS de `.precip-pane`.
 */
export function PrecipLayer({ grid, index }: Props) {
  const half = grid.step_deg / 2;

  const cells = useMemo(
    () =>
      grid.cells.flatMap((cell) => {
        const bin = precipBin(cell.mm[index]);
        if (!bin) return [];
        const bounds: Bounds = [
          [cell.lat - half, cell.lon - half],
          [cell.lat + half, cell.lon + half],
        ];
        return [{ key: `${cell.lat},${cell.lon}`, bounds, color: bin.color, opacity: bin.opacity }];
      }),
    [grid, index, half],
  );

  return (
    <Pane name="precip" style={{ zIndex: 300 }} className="precip-pane">
      {cells.map((cell) => (
        <Rectangle
          key={cell.key}
          bounds={cell.bounds}
          pane="precip"
          pathOptions={{ stroke: false, fillColor: cell.color, fillOpacity: cell.opacity, interactive: false }}
        />
      ))}
    </Pane>
  );
}