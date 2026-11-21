import { CheckList, LeverChip, ShowTheNumbers, StoreLinks } from "@/components/bits";
import { formatRupees } from "@/lib/format";
import type { Alert } from "@/lib/types";

export function alertAnchor(alert: Pick<Alert, "rank">): string {
  return `alert-${alert.rank}`;
}

export function AlertCard({ alert, knownStores }: { alert: Alert; knownStores: Set<string> }) {
  const isMarket = alert.scope === "city";
  return (
    <article
      id={alertAnchor(alert)}
      className="scroll-mt-4 rounded-lg border border-line bg-surface p-4 sm:p-6"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-full border-2 border-ink text-base font-semibold tabular-nums">
          <span className="sr-only">Rank </span>
          {alert.rank}
        </span>
        <LeverChip lever={alert.lever} />
        {isMarket ? (
          <span className="rounded-full border border-ink px-3 py-0.5 text-sm font-semibold">
            Market issue · {alert.store_ids.length} stores in {alert.city}
          </span>
        ) : null}
      </div>

      <h2 className="mt-4 text-xl font-semibold leading-snug tracking-tight sm:text-2xl">{alert.headline}</h2>

      {isMarket ? (
        <p className="mt-2 text-[0.95rem] text-muted">
          This covers several stores in {alert.city} at once, so it is reported once and not store by store.
        </p>
      ) : null}

      <p className="mt-3">
        <span className="font-semibold">Why: </span>
        {alert.cause}
      </p>

      <section className="mt-5 rounded-lg bg-slab p-4 text-slab-ink sm:p-5" aria-label="Action for today">
        <p className="text-sm font-semibold uppercase tracking-wider text-slab-label">Do this today</p>
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

      <dl className="mt-5 grid gap-x-8 gap-y-4 sm:grid-cols-2">
        <div>
          <dt className="text-sm text-muted">At stake</dt>
          <dd>
            <span className="text-2xl font-semibold tabular-nums">{formatRupees(alert.rupees_at_stake_weekly)}</span>{" "}
            <span className="text-muted">a week</span>
          </dd>
        </div>
        <div>
          <dt className="text-sm text-muted">Compared with</dt>
          <dd className="font-medium">{alert.benchmark_basis}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-sm text-muted">{alert.store_ids.length === 1 ? "Store" : "Stores"}</dt>
          <dd>
            <StoreLinks storeIds={alert.store_ids} known={knownStores} />
          </dd>
        </div>
      </dl>

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
