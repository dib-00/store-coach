import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AlertCard } from "@/components/alert-card";
import { AlertFilter } from "@/components/alert-filter";
import {
  BackLink,
  CheckList,
  EmptyNote,
  NoEngineRun,
  PageTitle,
  SectionTitle,
  StoreList,
} from "@/components/bits";
import { loadEngineOutput } from "@/lib/data";
import { formatDateRange, formatRupees } from "@/lib/format";
import { NO_RUN_PARAM, routeId, staticIds } from "@/lib/routes";
import {
  alertCap,
  findManager,
  findStore,
  managerSummaryLine,
  notJudgedReason,
  storeIdsWithPages,
  visibleAlerts,
} from "@/lib/rules";
import { LeverBadge } from "@/components/lever-badge";

type Props = { params: Promise<{ id: string }> };

export function generateStaticParams() {
  const data = loadEngineOutput();
  return staticIds(data?.area_managers.map((m) => m.area_manager_id) ?? []);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const id = routeId((await params).id);
  const manager = loadEngineOutput()?.area_managers.find((m) => m.area_manager_id === id);
  return { title: manager ? manager.name : "Area manager" };
}

export default async function ManagerPage({ params }: Props) {
  const id = routeId((await params).id);
  const data = loadEngineOutput();
  if (!data) {
    if (id !== NO_RUN_PARAM) notFound();
    return <NoEngineRun />;
  }
  const manager = findManager(data, id);
  if (!manager) notFound();

  const alerts = visibleAlerts(manager);
  const knownStores = storeIdsWithPages(data);
  const period = data.windows.current;
  const stores = manager.store_ids.map((storeId) => {
    const store = findStore(data, storeId);
    return {
      storeId,
      place: store ? store.city : null,
      hasPage: knownStores.has(storeId),
      notJudged: store ? notJudgedReason(store) : null,
    };
  });

  return (
    <>
      <BackLink href="/">All area managers</BackLink>
      <PageTitle title={manager.name}>
        <p>
          {manager.city} · {manager.store_ids.length === 1 ? "1 store" : `${manager.store_ids.length} stores`}
        </p>
        <p className="mt-1">
          Period measured: {formatDateRange(period.start, period.end)}. Each alert states what it is
          compared with.
        </p>
      </PageTitle>

      <p className="mb-8 rounded-lg border border-ink bg-surface px-4 py-3 text-lg font-semibold leading-snug">
        {managerSummaryLine(manager)}
      </p>

      {(manager.market_notes ?? []).map((note) => (
        <section
          key={note.note_id}
          className="mb-8 flex gap-3 rounded-xl border border-info-ink/25 bg-info-bg px-4 py-4 text-info-ink sm:px-5"
          aria-label={`Market note for ${note.city}`}
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className="mt-0.5 h-6 w-6 shrink-0">
            <circle cx="10" cy="10" r="9" fill="none" stroke="currentColor" strokeWidth="2" />
            <path d="M10 9v5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            <circle cx="10" cy="6" r="1.2" fill="currentColor" />
          </svg>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold uppercase tracking-wide">
              Market note · {note.city} · not a store alert
            </p>
            <p className="mt-2 text-lg font-semibold leading-snug text-ink">{note.headline}</p>
            <p className="mt-2 text-ink">{note.detail}</p>
            <details className="mt-3">
              <summary className="cursor-pointer text-sm font-medium">Show the numbers</summary>
              <div className="mt-2 text-sm text-ink">
                <CheckList checks={note.checks} />
              </div>
            </details>
          </div>
        </section>
      ))}

      <h2 className="mb-3 text-xl font-semibold tracking-tight">
        {alerts.length === 0
          ? "Alerts this week"
          : alerts.length === 1
            ? "1 alert this week"
            : `${alerts.length} alerts this week, biggest first`}
      </h2>
      {alerts.length === 0 ? (
        <section
          aria-label="All clear"
          className="flex items-start gap-4 rounded-xl border border-good-ink/30 bg-good-bg px-5 py-6 text-good-ink"
        >
          <svg aria-hidden="true" viewBox="0 0 20 20" className="mt-0.5 h-8 w-8 shrink-0">
            <circle cx="10" cy="10" r="9" fill="currentColor" />
            <path d="M6 10.5l2.5 2.5L14 7.5" fill="none" stroke="var(--good-bg)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <p className="text-xl font-semibold leading-snug">Nothing needs attention this week</p>
            <p className="mt-1 text-ink">
              The engine found nothing in these stores that it could tie to an action for today.
            </p>
          </div>
        </section>
      ) : (
        <AlertFilter
          items={alerts.map((alert) => ({
            key: alert.alert_id,
            lever: alert.lever,
            node: <AlertCard alert={alert} knownStores={knownStores} />,
          }))}
        />
      )}
      <p className="mt-3 text-sm text-muted">
        At most {alertCap(manager)} alerts are shown in a week, ranked by rupees at stake.
      </p>

      <SectionTitle>Held back this week</SectionTitle>
      {manager.held_back.length === 0 ? (
        <EmptyNote>Nothing was held back.</EmptyNote>
      ) : (
        <>
          <p className="mb-3 text-muted">
            The engine found these too, but did not send them as alerts. The reason is given for each.
          </p>
          <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
            {manager.held_back.map((held, index) => (
              <li key={`${index}-${held.headline}`} className="p-4">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <LeverBadge lever={held.lever} />
                  <span className="text-muted">
                    <span className="font-semibold tabular-nums text-ink">
                      {formatRupees(held.rupees_at_stake_weekly)}
                    </span>{" "}
                    a week
                  </span>
                </div>
                <p className="mt-2 font-semibold">{held.headline}</p>
                <p className="mt-1">
                  <span className="text-muted">Not sent because: </span>
                  {held.reason}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}

      <SectionTitle>Stores</SectionTitle>
      {manager.store_ids.length === 0 ? (
        <EmptyNote>No stores are listed for this area manager.</EmptyNote>
      ) : (
        <StoreList stores={stores} />
      )}
    </>
  );
}
