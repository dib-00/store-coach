"use client";

// The "Done" tick under an alert's action. No sign-in: anyone with the page can tick it.
// It is the only part of the site that talks to a server after the page has loaded, and it is
// optional. With no Supabase settings it renders nothing; if a request fails it says
// "Saving unavailable" in small print. The alert itself never depends on it.

import { useEffect, useState } from "react";
import {
  parseStatusRows,
  statusConfig,
  statusHeaders,
  statusQueryUrl,
  statusWriteBody,
  statusWriteHeaders,
  statusWriteUrl,
} from "@/lib/alert-status";

// Both are public values, inlined when the site is built. The anon key is public by design.
const config = statusConfig(process.env.NEXT_PUBLIC_SUPABASE_URL, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);

const REQUEST_TIMEOUT_MS = 8000;

// Every tick on a page asks at the same moment, so the ids are collected and sent as one request.
type Waiter = (done: boolean | null) => void; // null = could not be read
let waiting = new Map<string, Waiter[]>();
let flushTimer: ReturnType<typeof setTimeout> | null = null;

async function flush(): Promise<void> {
  flushTimer = null;
  const batch = waiting;
  waiting = new Map();
  if (!config || batch.size === 0) return;
  let ticks: Map<string, boolean> | null = null;
  try {
    const response = await fetch(statusQueryUrl(config, [...batch.keys()]), {
      headers: statusHeaders(config),
      cache: "no-store",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (response.ok) ticks = parseStatusRows(await response.json());
  } catch {
    ticks = null;
  }
  for (const [id, waiters] of batch) {
    const result = ticks ? (ticks.get(id) ?? false) : null;
    for (const waiter of waiters) waiter(result);
  }
}

function readTick(alertId: string): Promise<boolean | null> {
  return new Promise((resolve) => {
    waiting.set(alertId, [...(waiting.get(alertId) ?? []), resolve]);
    if (flushTimer === null) flushTimer = setTimeout(flush, 0);
  });
}

async function writeTick(alertId: string, done: boolean): Promise<boolean> {
  if (!config) return false;
  try {
    const response = await fetch(statusWriteUrl(config), {
      method: "POST",
      headers: statusWriteHeaders(config),
      body: statusWriteBody(alertId, done, new Date()),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    return response.ok;
  } catch {
    return false;
  }
}

type State =
  | { phase: "loading" }
  | { phase: "unavailable" }
  | { phase: "ready"; done: boolean; saving: boolean; failed: boolean };

export function DoneTick({ alertId }: { alertId: string }) {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    if (!config) return;
    let current = true;
    readTick(alertId).then((done) => {
      if (!current) return;
      setState(done === null ? { phase: "unavailable" } : { phase: "ready", done, saving: false, failed: false });
    });
    return () => {
      current = false;
    };
  }, [alertId]);

  if (!config) return null;

  if (state.phase === "unavailable") {
    return <p className="mt-3 text-sm text-muted">Saving unavailable</p>;
  }

  const ready = state.phase === "ready";
  const done = ready && state.done;

  async function onChange(next: boolean) {
    if (!ready || state.saving) return;
    const before = state.done;
    setState({ phase: "ready", done: next, saving: true, failed: false });
    const saved = await writeTick(alertId, next);
    setState({ phase: "ready", done: saved ? next : before, saving: false, failed: !saved });
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
      <label
        className={`inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-md border px-3 py-2 font-medium ${
          done ? "border-good-ink bg-good-bg text-good-ink" : "border-line"
        } ${ready ? "" : "text-muted"}`}
      >
        <input
          type="checkbox"
          className="h-5 w-5 accent-current"
          checked={done}
          disabled={!ready || state.saving}
          onChange={(event) => onChange(event.target.checked)}
        />
        {done ? "Done" : "Mark as done"}
      </label>
      {ready && state.failed ? (
        <span className="text-sm text-muted" role="status">
          Saving unavailable
        </span>
      ) : null}
    </div>
  );
}
