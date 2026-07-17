// Lightweight client telemetry -> POST /v1/events (INC-B11).
// Buffered, batched, silent-fail: telemetry must never break the app.
// Disable entirely with NEXT_PUBLIC_TELEMETRY=off.

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;
const DISABLED = process.env.NEXT_PUBLIC_TELEMETRY === "off";

const FLUSH_AFTER_MS = 3000;
const FLUSH_AT_COUNT = 20; // server caps batches at 50

type ClientEvent = {
  name: string;
  value?: number;
  meta?: Record<string, unknown>;
};

let buffer: ClientEvent[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

export function flushNow(useBeacon = false): void {
  if (buffer.length === 0) return;
  const body = JSON.stringify({ events: buffer.slice(0, 50) });
  buffer = [];
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  try {
    if (useBeacon && typeof navigator !== "undefined" && navigator.sendBeacon) {
      // Survives page unload. Beacons can't carry auth headers, so this path
      // only lands on auth-less self-hosts — still best-effort by design.
      navigator.sendBeacon(
        `${BASE_URL}/v1/events`,
        new Blob([body], { type: "application/json" })
      );
      return;
    }
    void fetch(`${BASE_URL}/v1/events`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { Authorization: `Bearer ${API_KEY}` } : {}),
      },
      body,
      keepalive: true,
    }).catch(() => {});
  } catch {
    // swallow — telemetry is a bonus, never a dependency
  }
}

export function track(
  name: string,
  value?: number,
  meta?: Record<string, unknown>
): void {
  if (DISABLED || typeof window === "undefined") return;
  buffer.push({ name, value, meta });
  if (buffer.length >= FLUSH_AT_COUNT) {
    flushNow();
    return;
  }
  if (!flushTimer) {
    flushTimer = setTimeout(() => {
      flushTimer = null;
      flushNow();
    }, FLUSH_AFTER_MS);
  }
}
