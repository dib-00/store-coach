import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { AlertCard } from "@/components/alert-card";
import {
  BackLink,
  EmptyNote,
  LeverChip,
  NoEngineRun,
  PageTitle,
  SectionTitle,
  StoreLinks,
} from "@/components/bits";
import { loadEngineOutput } from "@/lib/data";
import { formatDateRange, formatRupees } from "@/lib/format";
import { NO_RUN_PARAM, routeId, staticIds } from "@/lib/routes";
import { alertCap, findManager, storeIdsWithPages, visibleAlerts } from "@/lib/rules";

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

      <h2 className="mb-3 text-xl font-semibold tracking-tight">
        {alerts.length === 0
          ? "Alerts this week"
          : alerts.length === 1
            ? "1 alert this week"
            : `${alerts.length} alerts this week, biggest first`}
      </h2>
      {alerts.length === 0 ? (
        <EmptyNote>
          No alerts this week. The engine found nothing in these stores that it could tie to an action
          for today.
        </EmptyNote>
      ) : (
        <ol className="space-y-5">
          {alerts.map((alert) => (
            <li key={alert.alert_id}>
              <AlertCard alert={alert} knownStores={knownStores} />
            </li>
          ))}
        </ol>
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
                  <LeverChip lever={held.lever} />
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
        <p className="text-lg">
          <StoreLinks storeIds={manager.store_ids} known={knownStores} />
        </p>
      )}
    </>
  );
}
