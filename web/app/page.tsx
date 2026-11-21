import Link from "next/link";
import { EmptyNote, NoEngineRun, PageTitle, managerHref } from "@/components/bits";
import { loadEngineOutput } from "@/lib/data";
import { formatDate, formatDateRange, formatIstDateTime, formatRupees } from "@/lib/format";
import { rupeesAtStakeShown, visibleAlerts } from "@/lib/rules";

/** Public proof that the engine runs unattended: the history of its scheduled runs. */
const WORKFLOW_RUNS_URL = "https://github.com/dib-00/store-coach/actions";

export default function Home() {
  const data = loadEngineOutput();
  if (!data) return <NoEngineRun />;

  const period = data.windows.current;

  return (
    <>
      <PageTitle title="Which stores need you today?">
        <p>Pick your name. Period measured: {formatDateRange(period.start, period.end)}.</p>
      </PageTitle>

      <section aria-label="Engine run" className="mb-8 rounded-lg border border-line bg-surface px-5 py-4">
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

      {data.area_managers.length === 0 ? (
        <EmptyNote>The engine run lists no area managers.</EmptyNote>
      ) : (
        <ul className="space-y-3">
          {data.area_managers.map((manager) => {
            const shown = visibleAlerts(manager).length;
            return (
              <li key={manager.area_manager_id}>
                <Link
                  href={managerHref(manager.area_manager_id)}
                  className="flex flex-col gap-x-6 gap-y-2 rounded-lg border border-line bg-surface px-5 py-4 no-underline hover:border-ink sm:flex-row sm:items-center sm:justify-between"
                >
                  <span>
                    <span className="block text-xl font-semibold tracking-tight">{manager.name}</span>
                    <span className="block text-muted">{manager.city}</span>
                  </span>
                  <span className="text-left sm:text-right">
                    <span className="block font-semibold">
                      {shown === 0 ? "No alerts this week" : shown === 1 ? "1 alert this week" : `${shown} alerts this week`}
                    </span>
                    {shown > 0 ? (
                      <span className="block text-muted">
                        <span className="font-semibold tabular-nums text-ink">
                          {formatRupees(rupeesAtStakeShown(manager))}
                        </span>{" "}
                        a week at stake
                      </span>
                    ) : null}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

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
          Rupees at stake for a manager is the sum of the figures on the alerts shown to them.
        </p>
      </section>
    </>
  );
}
