import type { Metadata } from "next";
import Link from "next/link";
import {
  CheckList,
  Definition,
  EmptyNote,
  NoEngineRun,
  PageTitle,
  ShowTheNumbers,
  StoreLinks,
  managerHref,
} from "@/components/bits";
import { loadEngineOutput, loadHistoryExample } from "@/lib/data";
import { formatDate } from "@/lib/format";
import { afterFigure, beforeFigure, formatDateSpan, type Figure } from "@/lib/followup-view";
import { followUpsByManager, movedCounts, optionalText, storeIdsWithPages } from "@/lib/rules";
import type { FollowUp } from "@/lib/types";
import { LeverBadge } from "@/components/lever-badge";

export const metadata: Metadata = { title: "Follow-up" };

// The marker says what happened to the number and nothing more. "Not measurable" is its own
// outcome, with its own look, so a week that could not be measured is never read as a win or a loss.
const MOVED: Record<FollowUp["moved"], { label: string; mark: string; className: string }> = {
  improved: { label: "Improved", mark: "↑", className: "bg-good-bg text-good-ink" },
  no_change: { label: "No change", mark: "=", className: "bg-flat-bg text-flat-ink" },
  worse: { label: "Worse", mark: "↓", className: "bg-bad-bg text-bad-ink" },
  not_measurable: { label: "Not measurable", mark: "?", className: "border border-ink text-ink" },
};

function FigureCell({ term, figure }: { term: string; figure: Figure }) {
  return (
    <div className="px-3 py-3">
      <dt className="text-sm text-muted">
        {term}
        {figure.window ? <>: {formatDateSpan(figure.window.start, figure.window.end)}</> : null}
      </dt>
      <dd className="text-xl font-semibold tabular-nums sm:text-2xl">{figure.display}</dd>
      {figure.note ? <dd className="text-sm text-muted">({figure.note})</dd> : null}
      {figure.sample ? <dd className="text-sm text-muted">{figure.sample}</dd> : null}
    </div>
  );
}

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
        <LeverBadge lever={item.lever} />
        {item.store_ids.length > 0 ? (
          <span className="text-[0.95rem]">
            <StoreLinks storeIds={item.store_ids} known={knownStores} />
          </span>
        ) : null}
      </div>

      <p className="mt-4 text-lg font-semibold leading-snug sm:text-xl">{item.verdict}</p>

      <div className="mt-4">
        <p className="text-sm text-muted">{item.metric_label}</p>
        <dl className="mt-1 grid grid-cols-1 divide-y divide-line rounded-md border border-line sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          <FigureCell term="Before" figure={beforeFigure(item)} />
          <FigureCell term="After" figure={afterFigure(item)} />
          <div className="px-3 py-3">
            <dt className="text-sm text-muted">Target</dt>
            <dd className="text-xl font-semibold tabular-nums sm:text-2xl">{item.target_display}</dd>
          </div>
        </dl>
        {definition ? <Definition>{definition}</Definition> : null}
        <p className="mt-1 text-sm text-muted">
          Alert raised on data up to {formatDate(item.raised_as_of)}. Measured again on data up to{" "}
          {formatDate(item.measured_as_of)}.
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
  const example = loadHistoryExample();

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

      {example ? (
        <section aria-labelledby="fu-history" className="mt-16 border-t-4 border-line pt-8">
          <h2 id="fu-history" className="text-2xl font-semibold tracking-tight">
            Historical example (replayed from {formatDate(example.history.raised_as_of)})
          </h2>
          <p className="mb-2 mt-1 text-muted">
            Not a live result. This is a replay of the engine on earlier data (up to{" "}
            {formatDate(example.history.raised_as_of)}, then up to {formatDate(example.history.measured_as_of)}),
            to show that the follow-up detects real movement.
          </p>
          {example.history.note ? <p className="mb-4">{example.history.note}</p> : null}
          <FollowUpItem item={example.item} knownStores={knownStores} />
        </section>
      ) : null}
    </>
  );
}
