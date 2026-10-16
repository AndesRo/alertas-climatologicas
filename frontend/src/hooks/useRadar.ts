import { useEffect, useState } from "react";

interface RadarFrame {
  time: number;
  path: string;
}

interface RainViewerIndex {
  host: string;
  radar?: { past?: RadarFrame[] };
}

export interface RadarLayer {
  url: string;
  time: number;
}

/** Carga el fotograma más reciente disponible de RainViewer. */
export function useRadar(enabled: boolean) {
  const [radar, setRadar] = useState<RadarLayer | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!enabled) return;

    const controller = new AbortController();

    const load = async () => {
      try {
        const response = await fetch(
          "https://api.rainviewer.com/public/weather-maps.json",
          { signal: controller.signal }
        );

        if (!response.ok) throw new Error(String(response.status));

        const index = (await response.json()) as RainViewerIndex;
        const frames = index.radar?.past ?? [];
        const last = frames[frames.length - 1];

        if (!last) throw new Error("sin fotogramas");

        setRadar({
          url: `${index.host}${last.path}/256/{z}/{x}/{y}/2/1_1.png`,
          time: last.time,
        });
        setError(false);
      } catch {
        if (!controller.signal.aborted) setError(true);
      }
    };

    void load();
    const id = window.setInterval(() => void load(), 10 * 60_000);

    return () => {
      controller.abort();
      window.clearInterval(id);
    };
  }, [enabled]);

  return { radar: enabled ? radar : null, error };
}
