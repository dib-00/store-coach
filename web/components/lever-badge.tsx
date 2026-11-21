// The one colour-coded lever badge used everywhere. Each lever has its own
// background/ink pair (AA contrast in light and dark) and a distinct shape marker,
// so the lever is never told apart by colour alone.

import { leverLabel } from "@/lib/format";
import type { Lever } from "@/lib/types";

const LEVER_CLASS: Record<Lever, string> = {
  more_bills: "bg-bills-bg text-bills-ink border-bills-ink/30",
  bigger_baskets: "bg-baskets-bg text-baskets-ink border-baskets-ink/30",
  more_repeat: "bg-repeat-bg text-repeat-ink border-repeat-ink/30",
};

function Marker({ lever }: { lever: Lever }) {
  if (lever === "more_bills") {
    return (
      <svg aria-hidden="true" viewBox="0 0 10 10" className="h-2.5 w-2.5 shrink-0">
        <circle cx="5" cy="5" r="4.5" fill="currentColor" />
      </svg>
    );
  }
  if (lever === "bigger_baskets") {
    return (
      <svg aria-hidden="true" viewBox="0 0 10 10" className="h-2.5 w-2.5 shrink-0">
        <rect x="0.5" y="0.5" width="9" height="9" rx="1.5" fill="currentColor" />
      </svg>
    );
  }
  return (
    <svg aria-hidden="true" viewBox="0 0 10 10" className="h-2.5 w-2.5 shrink-0">
      <path d="M5 0.3 9.7 9.5H0.3Z" fill="currentColor" />
    </svg>
  );
}

export function LeverBadge({ lever }: { lever: Lever }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-0.5 text-sm font-semibold ${LEVER_CLASS[lever] ?? "border-line bg-flat-bg text-flat-ink"}`}
    >
      <Marker lever={lever} />
      {leverLabel(lever)}
    </span>
  );
}
