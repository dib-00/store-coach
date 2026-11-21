// The one place the site reads engine output. Server only: it reads a file from disk
// while the pages are being built, so the published site is plain static HTML.
//
// There is deliberately no fallback to sample data. If the file is missing or damaged
// the pages say that no engine run has been published.

import fs from "node:fs";
import path from "node:path";
import { parseEngineOutput } from "./parse.ts";
import { parseHistoryNote, type HistoryNote } from "./followup-view.ts";
import type { EngineOutput, FollowUp } from "./types.ts";

/** Reads and checks one engine output file. Returns null, with the reason logged, if it cannot be used. */
export function readEngineFile(file: string): EngineOutput | null {
  let text: string;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    console.warn(`[store-coach] no engine output found at ${file}`);
    return null;
  }
  const result = parseEngineOutput(text);
  if (!result.ok) {
    console.warn(`[store-coach] engine output at ${file} was rejected: ${result.reason}`);
    return null;
  }
  return result.data;
}

/**
 * STORE_COACH_DATA_FILE points the loader at another file, for development only.
 * It is ignored on Vercel, so a deployed site can only ever show the published file.
 */
export function developmentOverrideFile(env: Record<string, string | undefined> = process.env): string | null {
  const override = env.STORE_COACH_DATA_FILE?.trim();
  if (!override) return null;
  if (env.VERCEL) return null;
  return path.resolve(override);
}

let cached: { data: EngineOutput | null } | undefined;

export function loadEngineOutput(): EngineOutput | null {
  if (!cached) {
    const published = path.join(process.cwd(), "public", "data", "latest.json");
    cached = { data: readEngineFile(developmentOverrideFile() ?? published) };
  }
  return cached.data;
}

/** True when the pages are showing a development file instead of the published engine run. */
export function isDevelopmentData(): boolean {
  return developmentOverrideFile() !== null;
}

/**
 * The labelled historical example: web/public/data/history.json names one follow-up in an
 * earlier replayed run (public/data/runs/<measured_as_of>.json). Null, and the page shows no
 * example, when either file is missing or the follow-up is not in that run.
 */
export function loadHistoryExample(): { history: HistoryNote; item: FollowUp } | null {
  const dir = path.join(process.cwd(), "public", "data");
  let history: HistoryNote | null = null;
  try {
    history = parseHistoryNote(JSON.parse(fs.readFileSync(path.join(dir, "history.json"), "utf8")));
  } catch {
    return null;
  }
  if (!history) return null;
  const run = readEngineFile(path.join(dir, "runs", `${history.measured_as_of}.json`));
  if (!run || run.as_of !== history.measured_as_of) return null;
  const item = run.follow_ups.find(
    (f) => f.alert_id === history.alert_id && f.raised_as_of === history.raised_as_of,
  );
  return item ? { history, item } : null;
}
