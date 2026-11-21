import { CheckList, Definition, ShowTheNumbers, StoreLinks } from "@/components/bits";
import { DoneTick } from "@/components/done-tick";
import { formatRupees } from "@/lib/format";
import { optionalText } from "@/lib/rules";
import type { Alert } from "@/lib/types";
import { LeverBadge } from "@/components/lever-badge";

export function alertAnchor(alert: Pick<Alert, "rank">): string {
  return `alert-${alert.rank}`;
}

/** The two display strings for the follow-up metric, taken from the alert's own checks. */
function benchmarkBar(alert: Alert): { now: string; benchmark: string } | null {
  const fu = alert.follow_up;
  if (!fu || typeof fu.baseline_value !== "number" || typeof fu.target_value !== "number") return null;
  const find = (value: number) => alert.checks.find((c) => c.kind === fu.kind && c.value === value)?.display;
  const now = find(fu.baseline_value);
  const benchmark = find(fu.target_value);
  if (!now || !benchmark) return null;
  return { now, benchmark };
}

function NowVsBenchmark({ alert }: { alert: Alert }) {
  const bar = benchmarkBar(alert);
  if (!bar) return null;
  const { baseline_value: now, target_value: target, metric_label } = alert.follow_up;
  const max = Math.max(Math.abs(now), Math.abs(target));
  if (!(max > 0)) return null;
  const rows = [
    { label: "Now", display: bar.now, pct: (Math.abs(now) / max) * 100, cls: "bg-bad-ink" },
    { label: "Benchmark", display: bar.benchmark, pct: (Math.abs(target) / max) * 100, cls: "bg-muted" },
  ];
  return (
    <figure className="mt-4 rounded-lg border border-line px-3 py-3">
      <figcaption className="text-sm text-muted">{metric_label}</figcaption>
      <div className="mt-2 space-y-2">
        {rows.map((row) => (
          <div key={row.label} className="grid grid-cols-[5.5rem_1fr_auto] items-center gap-3 text-sm">
            <span className="font-semibold">{row.label}</span>
            <span className="block h-3 min-w-0 rounded-full bg-line">
              <span className={`block h-3 rounded-full ${row.cls}`} style={{ width: `${row.pct}%` }} />
            </span>
            <span className="font-semibold tabular-nums">{row.display}</span>
          </div>
        ))}
      </div>
    </figure>
  );
}

export function AlertCard({ alert, knownStores }: { alert: Alert; knownStores: Set<string> }) {
  const isMarket = alert.scope === "city";
  const definition = optionalText(alert.definition);
  return (
    <article
      id={alertAnchor(alert)}
      className="scroll-mt-28 rounded-xl border border-line bg-surface p-4 shadow-sm transition sm:p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-ink text-lg font-bold tabular-nums text-paper">
            <span className="sr-only">Rank </span>
            {alert.rank}
          </span>
          <LeverBadge lever={alert.lever} />
          {isMarket ? (
            <span className="rounded-full border border-ink px-3 py-0.5 text-sm font-semibold">
              Market issue · {alert.store_ids.length} stores in {alert.city}
            </span>
          ) : null}
        </div>
        <p>
          <span className="text-3xl font-bold tabular-nums tracking-tight">{formatRupees(alert.rupees_at_stake_weekly)}</span>{" "}
          <span className="text-muted">a week at stake</span>
        </p>
      </div>

      <h2 className="mt-4 text-lg font-semibold leading-snug tracking-tight sm:text-xl">{alert.headline}</h2>
      {definition ? <Definition>{definition}</Definition> : null}

      <p className="mt-2 text-[0.95rem]">
        <span className="text-muted">{alert.store_ids.length === 1 ? "Store: " : "Stores: "}</span>
        <StoreLinks storeIds={alert.store_ids} known={knownStores} />
      </p>

      {isMarket ? (
        <p className="mt-2 text-[0.95rem] text-muted">
          This covers several stores in {alert.city} at once, so it is reported once and not store by store.
        </p>
      ) : null}

      <NowVsBenchmark alert={alert} />

      <details className="mt-4 rounded-md border border-line">
        <summary className="px-3 py-3 font-medium">Why this is happening</summary>
        <p className="px-3 pb-4">{alert.cause}</p>
      </details>

      <details open className="mt-5 rounded-lg bg-slab text-slab-ink shadow-md">
        <summary className="px-4 pt-4 text-sm font-semibold uppercase tracking-wider text-slab-label sm:px-5">
          Do this today
        </summary>
        <section className="px-4 pb-4 sm:px-5 sm:pb-5" aria-label="Action for today">
        <p className="mt-2 text-xl font-semibold leading-snug sm:text-[1.4rem]">{alert.action.text}</p>
        <dl className="mt-4 space-y-2 border-t border-slab-line pt-3 text-[0.95rem]">
          <div className="flex gap-3">
            <dt className="w-14 shrink-0 font-semibold text-slab-muted">Who</dt>
            <dd>{alert.action.who}</dd>
          </div>
          <div className="flex gap-3">
            <dt className="w-14 shrink-0 font-semibold text-slab-muted">What</dt>
            <dd>{alert.action.what}</dd>
          </div>
          <div className="flex gap-3">
            <dt className="w-14 shrink-0 font-semibold text-slab-muted">When</dt>
            <dd>{alert.action.when}</dd>
          </div>
        </dl>
        </section>
      </details>

      <DoneTick alertId={alert.alert_id} />

      <p className="mt-4 text-[0.95rem]">
        <span className="text-muted">Compared with: </span>
        <span className="font-medium">{alert.benchmark_basis}</span>
      </p>

      <ShowTheNumbers>
        <div>
          <p className="text-sm text-muted">How rupees at stake is worked out</p>
          <p className="mt-1">{alert.arithmetic.formula}</p>
          <p className="mt-1 font-semibold tabular-nums">{alert.arithmetic.worked}</p>
        </div>
        <CheckList checks={alert.checks} />
      </ShowTheNumbers>
    </article>
  );
}
