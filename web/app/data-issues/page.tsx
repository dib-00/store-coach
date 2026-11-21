import type { Metadata } from "next";
import { EmptyNote, NoEngineRun, PageTitle } from "@/components/bits";
import { DataIssueItem } from "@/components/data-issue-item";
import { loadEngineOutput } from "@/lib/data";
import { storeIdsWithPages } from "@/lib/rules";

export const metadata: Metadata = { title: "Data issues" };

export default function DataIssuesPage() {
  const data = loadEngineOutput();
  if (!data) return <NoEngineRun />;

  const knownStores = storeIdsWithPages(data);

  return (
    <>
      <PageTitle title="Numbers that cannot be right">
        <p>
          These are faults in the data, not in the stores. They are listed here and are never sent as
          alerts. For each one, the page says what the engine did about it.
        </p>
      </PageTitle>

      {data.data_issues.length === 0 ? (
        <EmptyNote>The engine found no numbers that cannot be right in this run.</EmptyNote>
      ) : (
        <ul className="space-y-4">
          {data.data_issues.map((issue) => (
            <li key={issue.issue_id}>
              <DataIssueItem issue={issue} storeLink knownStores={knownStores} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
