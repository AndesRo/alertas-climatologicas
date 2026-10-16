export function timeAgo(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "sin datos";
  const diffMs = Math.max(0, now - new Date(iso).getTime());
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "hace instantes";
  if (minutes < 60) return `hace ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.round(hours / 24)} d`;
}

export function fmt(value: number | null | undefined, unit = "", digits = 0): string {
  if (value == null) return "—";
  return unit ? `${value.toFixed(digits)} ${unit}` : value.toFixed(digits);
}

/** "2026-10-15T14:00" -> "14h" (las horas del pronóstico vienen en hora local de la ciudad). */
export function hourLabel(time: string): string {
  return `${time.slice(11, 13)}h`;
}

/** "hoy 14:00", "mañana 06:00" respecto de la hora actual de la ciudad. */
export function dayHourLabel(time: string, reference: string): string {
  const day = time.slice(0, 10);
  const ref = reference.slice(0, 10);
  const word = day === ref ? "hoy" : day < ref ? "ayer" : "mañana";
  return `${word} ${time.slice(11, 16)}`;
}

export function clockFromEpoch(seconds: number): string {
  return new Date(seconds * 1000).toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" });
}
