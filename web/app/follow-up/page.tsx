import type { Metadata } from "next";
import Link from "next/link";
import {
  CheckList,
  Definition,
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
import { followUpsByManager, movedCounts, optionalText, storeIdsWithPages } from "@/lib/rules";
import type { FollowUp } from "@/lib/types";

export const metadata: Metadata = { title: "Follow-up" };

// The marker says what happened to the number and nothing more. "Not measurable" is its own
// outcome, with its own look, so a week that could not be measured is never read as a win or a loss.
const MOVED: Record<FollowUp["moved"], { label: string; mark: string; className: string }> = {
  improved: { label: "Improved", mark: "↑", className: "bg-good-bg text-good-ink" },
  no_change: { label: "No change", mark: "=", className: "bg-flat-bg text-flat-ink" },
  worse: { label: "Worse", mark: "↓", className: "bg-bad-bg text-bad-ink" },
  not_measurable: { label: "Not measurable", mark: "?", className: "border border-ink text-ink" },
};

function FollowUpItem({ item, knownStores }: { item: FollowUp; knownStores: Set<string> }) {
  const moved = MOVED[item.moved];
  const definition = optionalText(item.definition);
  return (
    <article className="rounded-lg border border-line bg-surface p-4 sm:p-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className={`rounded-full px-3 py-0.5 text-sm font-bold ${moved.className}`}>
          <span aria-hidden="true">{moved.mark} </span>
          {moved.label}
        </span>
        <LeverChip lever={item.lever} />
        {item.store_ids.length > 0 ? (
          <span className="text-[0.95rem]">
            <StoreLinks storeIds={item.store_ids} known={knownStores} />
          </span>
        ) : null}
      </div>

      <p className="mt-4 text-lg font-semibold leading-snug sm:text-xl">{item.verdict}</p>

      <div className="mt-4">
        <p className="text-sm text-muted">{item.metric_label}</p>
        <dl className="mt-1 grid grid-cols-3 divide-x divide-line rounded-md border border-line text-center">
          <div className="px-2 py-3">
            <dt className="text-sm text-muted">Before</dt>
            <dd className="text-xl font-semibold tabular-nums sm:text-2xl">{item.before_display}</dd>
          </div>
          <div className="px-2 py-3">
            <dt className="text-sm text-muted">After</dt>
            <dd className="text-xl font-semibold tabular-nums sm:text-2xl">{item.after_display}</dd>
          </div>
          <div className="px-2 py-3">
            <dt className="text-sm text-muted">Target</dt>
            <dd className="text-xl font-semibold tabular-nums sm:text-2xl">{item.target_display}</dd>
          </div>
        </dl>
        {definition ? <Definition>{definition}</Definition> : null}
        <p className="mt-1 text-sm text-muted">
          Before: data up to {formatDate(item.raised_as_of)}. After: data up to {formatDate(item.measured_as_of)}.
        </p>
      </div>

      <div className="mt-4 border-t border-line pt-3 text-[0.95rem]">
        <p>
          <span className="text-muted">The alert was: </span>
          {item.headline}
        </p>
        <p className="mt-1">
          <span className="text-muted">Action recommended: </span>
          {item.action_text}
        </p>
      </div>

      {item.checks.length > 0 ? (
        <ShowTheNumbers>
          <CheckList checks={item.checks} />
        </ShowTheNumbers>
      ) : null}
    </article>
  );
}

export default function FollowUpPage() {
  const data = loadEngineOutput();
  if (!data) return <NoEngineRun />;

  const knownStores = storeIdsWithPages(data);
  const groups = followUpsByManager(data);

  return (
    <>
      <PageTitle title="Did last week's actions work?">
        <p>
          A week after an alert, the engine measures the same number again and reports whether it moved.
          Every result is listed, including the ones that did not move, got worse or could not be measured.
        </p>
      </PageTitle>

      {groups.length === 0 ? (
        <EmptyNote>
          No follow-ups yet. They appear a week after an alert is raised, once there is a new week of
          data to compare with.
        </EmptyNote>
      ) : (
        <div className="space-y-12">
          {groups.map((group) => (
            <section key={group.area_manager_id} aria-labelledby={`fu-${group.area_manager_id}`}>
              <h2 id={`fu-${group.area_manager_id}`} className="text-2xl font-semibold tracking-tight">
                {group.manager ? (
                  <Link
                    href={managerHref(group.manager.area_manager_id)}
                    className="underline decoration-line decoration-2 hover:decoration-ink"
                  >
                    {group.manager.name}
                  </Link>
                ) : (
                  <>Area manager {group.area_manager_id}</>
                )}
              </h2>
              <p className="mb-4 mt-1 text-muted">
                {group.manager ? `${group.manager.city} · ` : null}
                {group.items.length === 1 ? "1 follow-up" : `${group.items.length} follow-ups`}:{" "}
                {movedCounts(group.items)
                  .map((entry) => `${entry.count} ${MOVED[entry.moved].label.toLowerCase()}`)
                  .join(", ")}
              </p>
              <ul className="space-y-5">
                {group.items.map((item) => (
                  <li key={`${item.alert_id}@${item.measured_as_of}`}>
                    <FollowUpItem item={item} knownStores={knownStores} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
