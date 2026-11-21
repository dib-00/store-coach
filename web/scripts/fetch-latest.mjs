// Runs before every build ("prebuild" in package.json). It lets the daily engine run reach the
// site without a Git commit: the engine publishes each run to the Supabase table `runs`, and this
// script copies the newest one over public/data/latest.json for this build only.
//
// The committed file is the safe default. This script replaces it only when the published run
//   - has schema_version 1,
//   - is for the same data date or a later one,
//   - was generated after the committed file, and
//   - passes the same checks the pages apply (lib/parse.ts).
// In every other case (settings missing, network error, timeout, bad reply, older run) it logs one
// line and leaves the committed file untouched. It never fails the build: it always exits 0.
//
// It reads NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY from the environment of the
// build (on Vercel, the project's environment variables). It does not read .env files, so a local
// build keeps the committed file unless the two variables are exported in the shell.
// The anon key is public by design. No other key belongs anywhere in web/.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const TIMEOUT_MS = 8000;

/** An ISO 8601 instant as milliseconds, or null. A timestamp with no zone is read as UTC. */
export function instantMs(value) {
  if (typeof value !== "string" || value.trim() === "") return null;
  const text = value.trim();
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/i.test(text);
  const ms = Date.parse(hasZone ? text : `${text}Z`);
  return Number.isNaN(ms) ? null : ms;
}

const isDay = (value) => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);

/**
 * Which engine run this build should show. Pure: no files, no network.
 *
 * @param {unknown} committed the parsed committed latest.json, or null if it is missing or unreadable
 * @param {unknown} remote the `output` of the newest row in `runs`, or null if there is none
 * @returns {{ use: "remote" | "committed", reason: string }}
 */
export function chooseLatest(committed, remote) {
  const keep = (reason) => ({ use: "committed", reason });
  if (typeof remote !== "object" || remote === null || Array.isArray(remote)) {
    return keep("no published run was found");
  }
  if (remote.schema_version !== 1) return keep("the published run is not schema_version 1");
  if (!isDay(remote.as_of)) return keep("the published run has no valid as_of date");
  const remoteMs = instantMs(remote.generated_at);
  if (remoteMs === null) return keep("the published run has no valid generated_at time");

  const usable = typeof committed === "object" && committed !== null && !Array.isArray(committed);
  const committedMs = usable ? instantMs(committed.generated_at) : null;
  if (!usable || committedMs === null) {
    return { use: "remote", reason: "there is no usable committed file" };
  }
  // YYYY-MM-DD compares correctly as text.
  if (isDay(committed.as_of) && remote.as_of < committed.as_of) {
    return keep(`the published run is for older data (${remote.as_of}, committed ${committed.as_of})`);
  }
  if (remoteMs <= committedMs) {
    return keep(`the published run is not newer (${remote.generated_at}, committed ${committed.generated_at})`);
  }
  return { use: "remote", reason: `the published run is newer (${remote.generated_at}, data up to ${remote.as_of})` };
}

/** The request for the newest run, or null when either setting is missing. */
export function latestRunRequest(env) {
  const url = (env.NEXT_PUBLIC_SUPABASE_URL ?? "").trim().replace(/\/+$/, "");
  const key = (env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "").trim();
  if (url === "" || key === "") return null;
  return {
    url: `${url}/rest/v1/runs?select=output,as_of,generated_at&order=as_of.desc,generated_at.desc&limit=1`,
    headers: { apikey: key, Authorization: `Bearer ${key}` },
  };
}

function readCommitted(file) {
  try {
    const text = fs.readFileSync(file, "utf8");
    return JSON.parse(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text);
  } catch {
    return null;
  }
}

/** The same checks the pages apply. Returns null if the text is acceptable, otherwise the reason. */
async function rejectedBecause(text) {
  const parseModule = pathToFileURL(path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "lib", "parse.ts"));
  const { parseEngineOutput } = await import(parseModule.href);
  const result = parseEngineOutput(text);
  return result.ok ? null : result.reason;
}

/**
 * Does the whole job and returns the one line to log. Never throws.
 *
 * @param {{ env?: Record<string, string | undefined>, file: string, fetchImpl?: typeof fetch,
 *           timeoutMs?: number, validate?: (text: string) => Promise<string | null> }} options
 * @returns {Promise<{ wrote: boolean, message: string }>}
 */
export async function fetchLatest({ env = process.env, file, fetchImpl = fetch, timeoutMs = TIMEOUT_MS, validate = rejectedBecause }) {
  const keep = (why) => ({ wrote: false, message: `kept the committed file: ${why}` });
  try {
    const request = latestRunRequest(env);
    if (!request) return keep("NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY is not set");

    const response = await fetchImpl(request.url, { headers: request.headers, signal: AbortSignal.timeout(timeoutMs) });
    if (!response.ok) return keep(`the runs table answered HTTP ${response.status}`);
    const rows = await response.json();
    if (!Array.isArray(rows)) return keep("the runs table did not answer with a list of rows");
    if (rows.length === 0) return keep("no published run was found");

    let remote = rows[0]?.output;
    if (typeof remote === "string") remote = JSON.parse(remote);

    const decision = chooseLatest(readCommitted(file), remote);
    if (decision.use !== "remote") return keep(decision.reason);

    const text = `${JSON.stringify(remote, null, 2)}\n`;
    const rejected = await validate(text);
    if (rejected !== null) return keep(`the published run failed the site's checks (${rejected})`);

    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text, "utf8");
    return { wrote: true, message: `using the published run for this build: ${decision.reason}` };
  } catch (error) {
    const name = error instanceof Error ? error.name : "";
    const why = name === "TimeoutError" || name === "AbortError" ? `no answer within ${timeoutMs / 1000} s` : String(error instanceof Error ? error.message : error);
    return keep(why);
  }
}

const runAsScript = process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url;
if (runAsScript) {
  const file = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "public", "data", "latest.json");
  fetchLatest({ file })
    .then((result) => console.log(`[store-coach] fetch-latest: ${result.message}`))
    .catch((error) => console.log(`[store-coach] fetch-latest: kept the committed file: ${error}`))
    .finally(() => {
      process.exitCode = 0;
    });
}
