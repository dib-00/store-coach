import type { Metadata } from "next";
import Link from "next/link";
import {
  CheckList,
  EmptyNote,
  LeverChip,
  NoEngineRun,
  PageTitle,
  ShowTheNumbers,
  StoreLinks,
  managerHref,
} from "@/components/bits";
import { loadEngineOutput } from "@/lib/data";
import { formatDate } from "@/lib/format";
import { findManager, storeIdsWithPages } from "@/lib/rules";
import type { FollowUp } from "@/lib/types";

export const metadata: Metadata = { title: "Follow-up" };

const MOVED: Record<FollowUp["moved"], { label: string; className: string }> = {
  improved: { label: "Improved", className: "bg-good-bg text-good-ink" },
  no_change: { label: "No change", className: "bg-flat-bg text-flat-ink" },
  worse: { label: "Worse", className: "bg-bad-bg text-bad-ink" },
  not_measurable: { label: "Not measurable", className: "border border-ink text-ink" },
};

export default function FollowUpPage() {
  const data = loadEngineOutput();
  if (!data) return <NoEngineRun />;

  const knownStores = storeIdsWithPages(data);

  return (
    <>
      <PageTitle title="Did last week's actions work?">
        <p>
          A week after an alert, the engine measures the same number again and reports whether it moved.
        </p>
      </PageTitle>

      {data.follow_ups.length === 0 ? (
        <EmptyNote>
          No follow-ups yet. They appear a week after an alert is raised, once there is a new week of
          data to compare with.
        </EmptyNote>
      ) : (
        <ul className="space-y-5">
          {data.follow_ups.map((item) => {
            const moved = MOVED[item.moved];
            const manager = findManager(data, item.area_manager_id);
            return (
              <li key={`${item.alert_id}@${item.measured_as_of}`}>
                <article className="rounded-lg border border-line bg-surface p-4 sm:p-6">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <span className={`rounded-full px-3 py-0.5 text-sm font-bold ${moved.className}`}>
                      {moved.label}
                    </span>
                    <LeverChip lever={item.lever} />
                  </div>

                  <p className="mt-4 text-sm text-muted">Alert raised on data up to {formatDate(item.raised_as_of)}</p>
                  <h2 className="mt-1 text-xl font-semibold leading-snug tracking-tight">{item.headline}</h2>

                  <p className="mt-3">
                    <span className="font-semibold">Action recommended: </span>
                    {item.action_text}
                  </p>

                  <div className="mt-5">
                    <p className="text-sm text-muted">{item.metric_label}</p>
                    <dl className="mt-1 grid grid-cols-3 divide-x divide-line rounded-md border border-line text-center">
                      <div className="px-2 py-3">
                        <dt className="text-sm text-muted">Before</dt>
                        <dd className="text-2xl font-semibold tabular-nums">{item.before_display}</dd>
                      </div>
                      <div className="px-2 py-3">
                        <dt className="text-sm text-muted">After</dt>
                        <dd className="text-2xl font-semibold tabular-nums">{item.after_display}</dd>
                      </div>
                      <div className="px-2 py-3">
                        <dt className="text-sm text-muted">Target</dt>
                        <dd className="text-2xl font-semibold tabular-nums">{item.target_display}</dd>
                      </div>
                    </dl>
                    <p className="mt-1 text-sm text-muted">Measured on data up to {formatDate(item.measured_as_of)}</p>
                  </div>

                  <p className="mt-4 text-lg font-semibold leading-snug">{item.verdict}</p>

                  <p className="mt-4 text-[0.95rem] text-muted">
                    {manager ? (
                      <>
                        <Link
                          href={managerHref(manager.area_manager_id)}
                          className="font-semibold text-ink underline decoration-line decoration-2 hover:decoration-ink"
                        >
                          {manager.name}
                        </Link>
                        {item.store_ids.length > 0 ? " · " : null}
                      </>
                    ) : null}
                    <span className="text-ink">
                      <StoreLinks storeIds={item.store_ids} known={knownStores} />
                    </span>
                  </p>

                  {item.checks.length > 0 ? (
                    <ShowTheNumbers>
                      <CheckList checks={item.checks} />
                    </ShowTheNumbers>
                  ) : null}
                </article>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
