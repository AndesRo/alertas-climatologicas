import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { LocationPanel } from "./components/LocationPanel";
import { MapView } from "./components/MapView";
import { SidePanel, type Layers } from "./components/SidePanel";
import { useDashboard } from "./hooks/useDashboard";
import { usePolling } from "./hooks/usePolling";
import { useRadar } from "./hooks/useRadar";
import type { Alert } from "./types";

export default function App() {
  const dashboard = useDashboard();
  const rules = usePolling(api.rules, 60 * 60_000);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedAlertKey, setSelectedAlertKey] = useState<string | null>(null);
  const [focus, setFocus] = useState<[number, number] | null>(null);
  const [layers, setLayers] = useState<Layers>({ radar: true, quakes: true });
  const { radar, error: radarFailed } = useRadar(layers.radar);

  const locations = useMemo(() => dashboard.data?.locations ?? [], [dashboard.data]);
  const quakes = useMemo(() => dashboard.data?.quakes ?? [], [dashboard.data]);
  const selected = locations.find((l) => l.id === selectedId);

  const selectLocation = useCallback(
    (id: string) => {
      const loc = locations.find((l) => l.id === id);
      setSelectedId(id);
      setSelectedAlertKey(null);
      if (loc) setFocus([loc.lat, loc.lon]);
    },
    [locations],
  );

  const selectAlert = useCallback((alert: Alert) => {
    setSelectedAlertKey(alert.key);
    setSelectedId(alert.location_id);
    setFocus([alert.lat, alert.lon]);
  }, []);

  const close = useCallback(() => {
    setSelectedId(null);
    setSelectedAlertKey(null);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  return (
    <div
      data-detail={selectedId ? "open" : "closed"}
      className="relative h-dvh w-full overflow-hidden bg-abyss text-foam"
    >
      <MapView
        locations={locations}
        quakes={quakes}
        showQuakes={layers.quakes}
        radarUrl={radar?.url ?? null}
        selectedId={selectedId}
        focus={focus}
        onSelectLocation={selectLocation}
      />

      <SidePanel
        alerts={dashboard.data?.alerts ?? null}
        status={dashboard.data?.status ?? null}
        loading={dashboard.loading}
        error={dashboard.error}
        onRetry={dashboard.reload}
        selectedKey={selectedAlertKey}
        onSelectAlert={selectAlert}
        layers={layers}
        onToggleLayer={(layer) => setLayers((l) => ({ ...l, [layer]: !l[layer] }))}
        radarFailed={radarFailed}
        radarTime={radar?.time ?? null}
        className={selectedId ? "max-lg:hidden" : ""}
      />

      {selectedId && (
        <LocationPanel
          key={selectedId}
          locationId={selectedId}
          summary={selected}
          rules={rules.data}
          onClose={close}
        />
      )}
    </div>
  );
}
