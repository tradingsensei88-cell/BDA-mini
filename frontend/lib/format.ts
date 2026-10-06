/**
 * Presentation formatters for the SOC dashboard.
 *
 * Every helper is locale- and timezone-independent (UTC math + manual month
 * names) so server-rendered markup and client hydration always agree.
 */

const MONTHS_SHORT = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

const DAYS_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const pad = (value: number, length = 2) => String(value).padStart(length, "0");

/** "14:32" (UTC). */
export function formatTimeUTC(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** "14:32:18" (UTC). */
export function formatClockUTC(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(
    d.getUTCSeconds(),
  )}`;
}

/** "Oct 6" (UTC). */
export function formatDayShortUTC(iso: string): string {
  const d = new Date(iso);
  return `${MONTHS_SHORT[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

/** "Mon" (UTC). */
export function formatWeekdayUTC(iso: string): string {
  return DAYS_SHORT[new Date(iso).getUTCDay()];
}

/** "Oct 6, 14:32" (UTC). */
export function formatDateTimeUTC(iso: string): string {
  const d = new Date(iso);
  return `${MONTHS_SHORT[d.getUTCMonth()]} ${d.getUTCDate()}, ${pad(
    d.getUTCHours(),
  )}:${pad(d.getUTCMinutes())}`;
}

/** "Oct 6, 2026" (UTC). */
export function formatDateUTC(iso: string): string {
  const d = new Date(iso);
  return `${MONTHS_SHORT[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}

/** "2026-10-06" (UTC) - matches <input type="date"> values. */
export function formatDayISOUTC(iso: string): string {
  const d = new Date(iso);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(
    d.getUTCDate(),
  )}`;
}

/** "14:00" label for a bucket-closing timestamp. */
export function formatBucketHourUTC(iso: string): string {
  return `${pad(new Date(iso).getUTCHours())}:00`;
}

/** "24.8K" / "1.28M" / "1.2B" - compact metric notation. */
export function formatCompact(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 10_000) return `${(value / 1_000).toFixed(1)}K`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(2)}K`;
  return String(Math.round(value));
}

/** "824 B" / "412 KB" / "12.4 MB" / "3.8 GB". */
export function formatBytes(bytes: number): string {
  if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(2)} GB`;
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
  if (bytes >= 1_024) return `${(bytes / 1_024).toFixed(1)} KB`;
  return `${Math.round(bytes)} B`;
}

/** "96.7%" with a configurable fraction-digit count. */
export function formatPercent(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`;
}

/**
 * Relative label like "just now" / "42s ago" / "3m ago" / "2h ago".
 * `nowMs` is only available after mount, keeping SSR output deterministic.
 */
export function formatAgo(iso: string | number, nowMs: number): string {
  const then = typeof iso === "number" ? iso : Date.parse(iso);
  const seconds = Math.max(0, Math.round((nowMs - then) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

/** Clamp helper used by live-jittered metric values. */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Tailwind text color class for a 0-100 risk score. */
export function riskTextClass(risk: number): string {
  if (risk >= 85) return "text-severity-critical";
  if (risk >= 70) return "text-severity-high";
  if (risk >= 50) return "text-severity-medium";
  return "text-severity-low";
}

/** Tailwind background class for a 0-100 risk score bar. */
export function riskBarClass(risk: number): string {
  if (risk >= 85) return "bg-severity-critical";
  if (risk >= 70) return "bg-severity-high";
  if (risk >= 50) return "bg-severity-medium";
  return "bg-severity-low";
}

/** Percentage value (0-100) of `part / total`, guarding against /0. */
export function percentOf(part: number, total: number, digits = 1): number {
  if (total <= 0) return 0;
  return Number(((part / total) * 100).toFixed(digits));
}
