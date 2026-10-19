import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { LocationPanel } from "./components/LocationPanel";
import { MapView } from "./components/MapView";
import { PrecipControl } from "./components/PrecipControl";
import { SidePanel, type Layers, type PrecipStatus } from "./components/SidePanel";
import { useDashboard } from "./hooks/useDashboard";
import { usePolling } from "./hooks/usePolling";
import { useRadar } from "./hooks/useRadar";
import { planPrecip } from "./lib/precip";
import type { Alert } from "./types";

export default function App() {
  const dashboard = useDashboard();
  const rules = usePolling(api.rules, 60 * 60_000);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedAlertKey, setSelectedAlertKey] = useState<string | null>(null);
  const [focus, setFocus] = useState<[number, number] | null>(null);
  // El radar de RainViewer casi no tiene datos sobre Chile, así que arranca apagado y la
  // precipitación prevista por el modelo es la capa principal.
  const [layers, setLayers] = useState<Layers>({ precip: true, radar: false, quakes: true });
  const { radar, error: radarFailed } = useRadar(layers.radar);

  // La grilla cambia una vez por hora: consultarla cada 10 minutos basta.
  const precip = usePolling(api.precip, 10 * 60_000);
  const [precipOffset, setPrecipOffset] = useState(0);
  // Se recalcula en cada render a propósito: depende del reloj, no solo de los datos.
  const precipPlan = planPrecip(precip.data);
  const offset = precipPlan ? Math.min(precipOffset, precipPlan.max) : 0;
  const precipStatus: PrecipStatus = !precip.data
    ? precip.error
      ? "error"
      : "loading"
    : precipPlan
      ? "ready"
      : "stale";
  const showPrecip = layers.precip && precip.data !== null && precipPlan !== null;

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
        precip={showPrecip ? precip.data : null}
        precipIndex={showPrecip && precipPlan ? precipPlan.start + offset : null}
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
        precipStatus={precipStatus}
        className={selectedId ? "max-lg:hidden" : ""}
      />

      {showPrecip && precip.data && precipPlan && (
        <PrecipControl
          grid={precip.data}
          plan={precipPlan}
          offset={offset}
          onOffset={setPrecipOffset}
          className={selectedId ? "max-lg:hidden" : ""}
        />
      )}

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