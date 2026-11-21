import { CheckList, ShowTheNumbers, StoreLinks } from "@/components/bits";
import { formatDate, formatDateRange } from "@/lib/format";
import type { DataIssue } from "@/lib/types";

export function DataIssueItem({
  issue,
  storeLink,
  knownStores,
}: {
  issue: DataIssue;
  storeLink: boolean;
  knownStores: Set<string>;
}) {
  const dates =
    issue.first_date === issue.last_date
      ? formatDate(issue.first_date)
      : formatDateRange(issue.first_date, issue.last_date);
  return (
    <article className="rounded-lg border border-line bg-surface p-4 sm:p-5">
      <h3 className="text-lg font-semibold leading-snug tracking-tight">{issue.title}</h3>
      <p className="mt-1 text-sm text-muted">
        {storeLink ? (
          <>
            <StoreLinks storeIds={[issue.store_id]} known={knownStores} /> ·{" "}
          </>
        ) : null}
        {dates} · {issue.days_affected === 1 ? "1 day affected" : `${issue.days_affected} days affected`}
      </p>
      <p className="mt-3">{issue.detail}</p>
      <p className="mt-3 rounded-md bg-flat-bg px-3 py-2 text-flat-ink">
        <span className="font-semibold">What the engine did: </span>
        {issue.handling}
      </p>
      {issue.checks.length > 0 ? (
        <ShowTheNumbers>
          <CheckList checks={issue.checks} />
        </ShowTheNumbers>
      ) : null}
    </article>
  );
}
