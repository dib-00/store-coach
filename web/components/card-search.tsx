"use client";

// Filters the salesperson cards by name, case-insensitive. Pure show/hide on the client.

import { useId, useState } from "react";

export function CardSearch({ items }: { items: { key: string; name: string; node: React.ReactNode }[] }) {
  const [query, setQuery] = useState("");
  const inputId = useId();
  const q = query.trim().toLowerCase();
  const shown = q === "" ? items : items.filter((item) => item.name.toLowerCase().includes(q));
  return (
    <>
      <div className="mb-4">
        <label htmlFor={inputId} className="mb-1 block text-sm font-medium text-muted">
          Find a salesperson
        </label>
        <input
          id={inputId}
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Type a name"
          autoComplete="off"
          className="min-h-11 w-full rounded-lg border border-line bg-surface px-3 py-2 text-base text-ink placeholder:text-muted hover:border-ink"
        />
      </div>
      {shown.length === 0 ? (
        <p role="status" className="rounded-lg border border-dashed border-line px-4 py-5 text-muted">
          No salesperson card matches &ldquo;{query.trim()}&rdquo;.
        </p>
      ) : (
        <div className="space-y-4">
          {shown.map((item) => (
            <div key={item.key}>{item.node}</div>
          ))}
        </div>
      )}
    </>
  );
}
