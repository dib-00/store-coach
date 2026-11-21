"use client";

// Lever filter chips above the alert list. Pure show/hide on the client:
// the list it receives is already capped, so the cap still applies.

import { useState } from "react";
import { leverLabel } from "@/lib/format";
import type { Lever } from "@/lib/types";

export function AlertFilter({
  items,
}: {
  items: { key: string; lever: Lever; node: React.ReactNode }[];
}) {
  const [active, setActive] = useState<Lever | "all">("all");
  const levers = [...new Set(items.map((item) => item.lever))];
  const shown = active === "all" ? items : items.filter((item) => item.lever === active);
  const chip = (value: Lever | "all", label: string) => (
    <button
      key={value}
      type="button"
      aria-pressed={active === value}
      onClick={() => setActive(value)}
      className={`min-h-10 rounded-full border px-4 py-1.5 text-sm font-semibold transition hover:border-ink active:scale-95 ${
        active === value ? "border-ink bg-ink text-paper" : "border-line bg-surface text-ink"
      }`}
    >
      {label}
    </button>
  );
  return (
    <>
      {levers.length > 1 ? (
        <div role="group" aria-label="Filter alerts by lever" className="mb-4 flex flex-wrap gap-2">
          {chip("all", "All")}
          {levers.map((lever) => chip(lever, leverLabel(lever)))}
        </div>
      ) : null}
      <ol className="space-y-5">
        {shown.map((item) => (
          <li key={item.key}>{item.node}</li>
        ))}
      </ol>
    </>
  );
}
