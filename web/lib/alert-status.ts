// The "Done" tick on an alert is kept in one Supabase table, read and written through PostgREST:
//   alert_status(alert_id text primary key, done boolean, updated_at timestamptz)
// This file builds the requests and reads the replies. Pure functions only (no fetch, no React),
// so `node --test` can run them directly. The tick is a convenience: the site works without it.
//
// The only key used is the Supabase anon key, which is public by design. No other key belongs in web/.

export interface StatusConfig {
  url: string; // project URL, no trailing slash
  anonKey: string;
}

/** Both values are needed. If either is missing or the URL is not http(s), there is no tick at all. */
export function statusConfig(url: string | undefined, anonKey: string | undefined): StatusConfig | null {
  const cleanUrl = (url ?? "").trim().replace(/\/+$/, "");
  const cleanKey = (anonKey ?? "").trim();
  if (cleanUrl === "" || cleanKey === "") return null;
  if (!/^https?:\/\/[^\s/]+/i.test(cleanUrl)) return null;
  return { url: cleanUrl, anonKey: cleanKey };
}

export function statusHeaders(config: StatusConfig): Record<string, string> {
  return { apikey: config.anonKey, Authorization: `Bearer ${config.anonKey}` };
}

/** PostgREST wants a value holding commas, colons or spaces in double quotes inside in.(...). */
function quoted(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/** GET this to learn which of the given alerts are ticked. */
export function statusQueryUrl(config: StatusConfig, alertIds: string[]): string {
  const list = [...new Set(alertIds)].map(quoted).join(",");
  return `${config.url}/rest/v1/alert_status?select=alert_id,done&alert_id=in.(${encodeURIComponent(list)})`;
}

/** POST one row here to set or clear a tick. */
export function statusWriteUrl(config: StatusConfig): string {
  return `${config.url}/rest/v1/alert_status`;
}

/** merge-duplicates makes the POST an upsert on the primary key, so a second tick updates the row. */
export function statusWriteHeaders(config: StatusConfig): Record<string, string> {
  return {
    ...statusHeaders(config),
    "Content-Type": "application/json",
    Prefer: "resolution=merge-duplicates,return=minimal",
  };
}

export function statusWriteBody(alertId: string, done: boolean, now: Date): string {
  return JSON.stringify({ alert_id: alertId, done, updated_at: now.toISOString() });
}

/**
 * The reply to the GET, as alert id -> ticked. An alert with no row is simply absent (not ticked).
 * Returns null if the reply is not the list of rows it should be, which the caller treats as a failure.
 */
export function parseStatusRows(reply: unknown): Map<string, boolean> | null {
  if (!Array.isArray(reply)) return null;
  const ticks = new Map<string, boolean>();
  for (const row of reply) {
    if (typeof row !== "object" || row === null) return null;
    const { alert_id: id, done } = row as { alert_id?: unknown; done?: unknown };
    if (typeof id !== "string") return null;
    ticks.set(id, done === true);
  }
  return ticks;
}
