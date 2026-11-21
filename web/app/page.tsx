import Link from "next/link";
import { EmptyNote, NoEngineRun, PageTitle, managerHref } from "@/components/bits";
import { loadEngineOutput } from "@/lib/data";
import { countChecks } from "@/lib/count-checks";
import { formatDate, formatDateRange, formatIstDateTime, formatRupees } from "@/lib/format";
import { rupeesAtStakeShown, visibleAlerts } from "@/lib/rules";

/** Public proof that the engine runs unattended: the history of its scheduled runs. */
const WORKFLOW_RUNS_URL = "https://github.com/dib-00/store-coach/actions";

export default function Home() {
  const data = loadEngineOutput();
  if (!data) return <NoEngineRun />;

  const period = data.windows.current;
  const alertsThisWeek = data.area_managers.reduce((n, m) => n + visibleAlerts(m).length, 0);
  const rupeesThisWeek = data.area_managers.reduce((n, m) => n + rupeesAtStakeShown(m), 0);
  const tiles = [
    { label: "Alerts this week", value: alertsThisWeek.toLocaleString("en-IN") },
    { label: "Rupees at stake a week", value: formatRupees(rupeesThisWeek) },
    { label: "Stores covered", value: data.stores.length.toLocaleString("en-IN") },
    { label: "Figures verified in this run", value: countChecks(data).toLocaleString("en-IN") },
  ];

  return (
    <>
      <PageTitle title="Which stores need you today?">
        <p className="text-lg text-ink">
          Store Coach reads Manyavar&apos;s store data every morning and tells each area manager which
          stores are slipping, why, and one thing to do about it today.
        </p>
        <p className="mt-2">
          Pick your name below. Period measured: {formatDateRange(period.start, period.end)}.{" "}
          <Link
            href="/method"
            className="font-medium text-ink underline decoration-line decoration-2 hover:decoration-ink"
          >
            How the numbers are checked
          </Link>
        </p>
      </PageTitle>

      <section aria-label="This week at a glance" className="-mt-2 mb-10">
        <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {tiles.map((tile) => (
            <div key={tile.label} className="flex flex-col-reverse justify-end rounded-xl border border-line bg-surface px-4 py-3">
              <dt className="mt-1 text-sm leading-snug text-muted">{tile.label}</dt>
              <dd className="whitespace-nowrap text-2xl font-semibold tabular-nums tracking-tight sm:text-3xl lg:text-2xl">
                {tile.value}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <h2 className="mb-3 text-xl font-semibold tracking-tight">Area managers</h2>

      {data.area_managers.length === 0 ? (
        <EmptyNote>The engine run lists no area managers.</EmptyNote>
      ) : (
        <ul className="space-y-3">
          {data.area_managers.map((manager) => {
            const shown = visibleAlerts(manager).length;
            const storeCount = manager.store_ids.length;
            return (
              <li key={manager.area_manager_id}>
                <Link
                  href={managerHref(manager.area_manager_id)}
                  className={`group flex flex-col gap-x-6 gap-y-3 rounded-xl border px-5 py-4 no-underline shadow-sm transition hover:-translate-y-0.5 hover:border-ink hover:shadow-md active:translate-y-0 active:bg-paper active:shadow-none sm:flex-row sm:items-center sm:justify-between ${shown === 0 ? "border-good-ink/30 bg-good-bg/40" : "border-line bg-surface"}`}
                >
                  <span className="min-w-0">
                    <span className="block text-xl font-semibold tracking-tight group-hover:underline">{manager.name}</span>
                    <span className="block text-muted">
                      {manager.city} · {storeCount === 1 ? "1 store" : `${storeCount} stores`}
                    </span>
                  </span>
                  {shown === 0 ? (
                    <span className="inline-flex items-center gap-2 font-semibold text-good-ink">
                      <svg aria-hidden="true" viewBox="0 0 20 20" className="h-5 w-5 shrink-0">
                        <circle cx="10" cy="10" r="9" fill="currentColor" />
                        <path d="M6 10.5l2.5 2.5L14 7.5" fill="none" stroke="var(--good-bg)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      All clear: nothing needs attention this week
                    </span>
                  ) : (
                    <span className="flex items-center gap-4 sm:text-right">
                      <span>
                        <span className="block font-semibold">
                          {shown === 1 ? "1 alert this week" : `${shown} alerts this week`}
                        </span>
                        <span className="block text-muted">
                          <span className="font-semibold tabular-nums text-ink">
                            {formatRupees(rupeesAtStakeShown(manager))}
                          </span>{" "}
                          a week at stake
                        </span>
                      </span>
                      <span aria-hidden="true" className="ml-auto text-2xl text-muted transition group-hover:translate-x-1 group-hover:text-ink">
                        →
                      </span>
                    </span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      <section aria-label="Engine run" className="mt-10 rounded-lg border border-line bg-surface px-5 py-4">
        <p className="font-semibold">
          The engine runs on its own every morning. Nobody has to press a button.
        </p>
        <dl className="mt-3 grid gap-x-8 gap-y-2 sm:grid-cols-2">
          <div>
            <dt className="text-sm text-muted">Last ran</dt>
            <dd className="font-semibold tabular-nums">{formatIstDateTime(data.generated_at)}</dd>
          </div>
          <div>
            <dt className="text-sm text-muted">Data up to</dt>
            <dd className="font-semibold tabular-nums">{formatDate(data.as_of)}</dd>
          </div>
        </dl>
        <p className="mt-3 text-[0.95rem]">
          <a
            href={WORKFLOW_RUNS_URL}
            className="font-medium underline decoration-line decoration-2 hover:decoration-ink"
          >
            See the record of every run on GitHub Actions
          </a>
        </p>
      </section>

      <section className="mt-12 text-[0.95rem] text-muted">
        <h2 className="font-semibold text-ink">How to read this</h2>
        <p className="mt-2">
          Each area manager gets at most five alerts a week, ranked by rupees at stake. Each alert names
          one of three levers and one action the store can take today.
        </p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>
            <span className="font-medium text-ink">More bills:</span> conversion, bills divided by
            walk-ins.
          </li>
          <li>
            <span className="font-medium text-ink">Bigger baskets:</span> items per bill.
          </li>
          <li>
            <span className="font-medium text-ink">More repeat:</span> a customer billing again 30 or
            more days after their first bill.
          </li>
        </ul>
        <p className="mt-2">
          Rupees at stake for a manager is the sum of the figures on the alerts shown to them.{" "}
          <Link href="/method" className="font-medium text-ink underline decoration-line decoration-2 hover:decoration-ink">
            How every number is worked out and checked
          </Link>
          .
        </p>
      </section>
    </>
  );
}
