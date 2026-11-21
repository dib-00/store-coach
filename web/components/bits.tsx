// Small shared pieces used on several pages. All server-rendered, no client JavaScript.

import Link from "next/link";
import type { Check } from "@/lib/types";

/** Shown on every page when there is no usable engine output. */
export function NoEngineRun() {
  return (
    <section className="rounded-lg border border-line bg-surface p-6">
      <h1 className="text-2xl font-semibold tracking-tight">No engine run has been published yet</h1>
      <p className="mt-3 text-muted">
        Store Coach shows only what its engine has computed from store data. Until the first run is
        published there is nothing to show here, and this site never fills the gap with sample numbers.
      </p>
    </section>
  );
}

export function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-line px-4 py-5 text-muted">{children}</p>
  );
}

export function PageTitle({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">{title}</h1>
      {children ? <div className="mt-3 text-muted">{children}</div> : null}
    </div>
  );
}

export function SectionTitle({ children, id }: { children: React.ReactNode; id?: string }) {
  return (
    <h2 id={id} className="mb-3 mt-12 text-xl font-semibold tracking-tight">
      {children}
    </h2>
  );
}

export function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <p className="mb-5 text-[0.95rem]">
      <Link href={href} className="font-medium underline decoration-line decoration-2 hover:decoration-ink">
        <span aria-hidden="true">← </span>
        {children}
      </Link>
    </p>
  );
}

export function storeHref(storeId: string): string {
  return `/store/${encodeURIComponent(storeId)}`;
}

export function managerHref(managerId: string): string {
  return `/manager/${encodeURIComponent(managerId)}`;
}

/** Store ids as links. An id with no store page is shown as plain text so there are no dead links. */
export function StoreLinks({ storeIds, known }: { storeIds: string[]; known: Set<string> }) {
  return (
    <span className="inline-flex flex-wrap gap-x-3 gap-y-1">
      {storeIds.map((id) =>
        known.has(id) ? (
          <Link
            key={id}
            href={storeHref(id)}
            className="font-semibold underline decoration-line decoration-2 hover:decoration-ink"
          >
            {id}
          </Link>
        ) : (
          <span key={id} className="font-semibold">
            {id}
          </span>
        ),
      )}
    </span>
  );
}

/** Label and value pairs, shown exactly as the engine formatted them. */
export function CheckList({ checks }: { checks: Check[] }) {
  if (checks.length === 0) return null;
  return (
    <dl className="divide-y divide-line border-y border-line">
      {checks.map((check) => (
        <div key={check.id} className="flex items-baseline justify-between gap-4 py-2">
          <dt className="min-w-0 text-muted">{check.label}</dt>
          <dd className="max-w-[55%] text-right font-semibold tabular-nums [overflow-wrap:break-word]">
            {check.display}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** The native expander used wherever a figure can be checked by hand. */
export function ShowTheNumbers({ children }: { children: React.ReactNode }) {
  return (
    <details className="mt-4 rounded-md border border-line">
      <summary className="px-3 py-3 font-medium">Show the numbers</summary>
      <div className="space-y-4 px-3 pb-4 text-[0.95rem]">{children}</div>
    </details>
  );
}

/**
 * The engine's one-sentence definition of a figure, in small print.
 * Placed right beside the numbers it defines, and never inside a salesperson card's 60 words.
 */
export function Definition({ children, className = "mt-1" }: { children: React.ReactNode; className?: string }) {
  return (
    <p className={`${className} text-sm text-muted`}>
      <span className="font-semibold">Definition: </span>
      {children}
    </p>
  );
}

/** A store that is not judged this run, and the reason. Never shown without the reason. */
export function NotJudged({ reason }: { reason: string }) {
  return (
    <>
      <span className="rounded-full bg-warn-bg px-3 py-0.5 text-sm font-semibold text-warn-ink">Not judged</span>{" "}
      <span>{reason}</span>
    </>
  );
}

/** A manager's stores, one per line, each with its not-judged reason beside it when there is one. */
export function StoreList({
  stores,
}: {
  stores: { storeId: string; place: string | null; hasPage: boolean; notJudged: string | null }[];
}) {
  return (
    <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
      {stores.map((store) => (
        <li key={store.storeId} className="px-4 py-3">
          <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            {store.hasPage ? (
              <Link
                href={storeHref(store.storeId)}
                className="text-lg font-semibold underline decoration-line decoration-2 hover:decoration-ink"
              >
                {store.storeId}
              </Link>
            ) : (
              <span className="text-lg font-semibold">{store.storeId}</span>
            )}
            {store.place ? <span className="text-muted">{store.place}</span> : null}
          </p>
          {store.notJudged ? (
            <p className="mt-1 text-[0.95rem]">
              <NotJudged reason={store.notJudged} />
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
