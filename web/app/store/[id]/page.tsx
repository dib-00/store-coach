import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { alertAnchor } from "@/components/alert-card";
import {
  BackLink,
  CheckList,
  Definition,
  EmptyNote,
  LeverChip,
  NoEngineRun,
  PageTitle,
  SectionTitle,
  ShowTheNumbers,
  managerHref,
} from "@/components/bits";
import { DataIssueItem } from "@/components/data-issue-item";
import { loadEngineOutput } from "@/lib/data";
import { formatDate } from "@/lib/format";
import { NO_RUN_PARAM, routeId, staticIds } from "@/lib/routes";
import {
  MAX_CARD_WORDS,
  cardView,
  cardsForStore,
  dataIssuesForStore,
  findManager,
  findStore,
  notJudgedReason,
  optionalText,
  visibleAlerts,
} from "@/lib/rules";
import type { Card } from "@/lib/types";

type Props = { params: Promise<{ id: string }> };

export function generateStaticParams() {
  const data = loadEngineOutput();
  return staticIds(data?.stores.map((s) => s.store_id) ?? []);
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const id = routeId((await params).id);
  const store = loadEngineOutput()?.stores.find((s) => s.store_id === id);
  return { title: store ? `Store ${store.store_id}` : "Store" };
}

function SalespersonCard({ card }: { card: Card }) {
  const view = cardView(card);
  const definition = optionalText(card.definition);
  return (
    <article className="rounded-lg border border-line bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <h3 className="text-lg font-semibold tracking-tight">{card.salesperson_name}</h3>
        <LeverChip lever={card.lever} />
      </div>
      {view.status === "show" ? (
        <>
          <div className="mt-3 rounded-md border-l-4 border-ink bg-paper px-4 py-3">
            <p className="text-lg leading-relaxed">{view.text}</p>
            <p className="mt-2 text-sm font-medium text-muted">
              {view.words} of {MAX_CARD_WORDS} words
            </p>
          </div>
          <p className="mt-3 text-[0.95rem] text-muted">
            Peer named: <span className="font-semibold text-ink">{card.peer.name}</span>, same store
          </p>
          {definition ? <Definition>{definition}</Definition> : null}
          {card.checks.length > 0 ? (
            <ShowTheNumbers>
              <CheckList checks={card.checks} />
            </ShowTheNumbers>
          ) : null}
        </>
      ) : (
        <p className="mt-3 rounded-md bg-warn-bg px-3 py-2 font-medium text-warn-ink">
          Card withheld: over {MAX_CARD_WORDS} words ({view.words} words). It is not shown until the
          engine sends a shorter one.
        </p>
      )}
    </article>
  );
}

export default async function StorePage({ params }: Props) {
  const id = routeId((await params).id);
  const data = loadEngineOutput();
  if (!data) {
    if (id !== NO_RUN_PARAM) notFound();
    return <NoEngineRun />;
  }
  const store = findStore(data, id);
  if (!store) notFound();

  const manager = findManager(data, store.area_manager_id);
  const cards = cardsForStore(data, store.store_id);
  const issues = dataIssuesForStore(data, store.store_id);
  const alerts = manager ? visibleAlerts(manager).filter((a) => a.store_ids.includes(store.store_id)) : [];
  const active = store.salespeople.filter((p) => p.active);
  const inactive = store.salespeople.filter((p) => !p.active);
  const notJudged = notJudgedReason(store);

  return (
    <>
      {manager ? (
        <BackLink href={managerHref(manager.area_manager_id)}>{manager.name}</BackLink>
      ) : (
        <BackLink href="/">All area managers</BackLink>
      )}
      <PageTitle title={`Store ${store.store_id}`}>
        {notJudged ? (
          <div className="mb-5 rounded-lg bg-warn-bg px-4 py-3 text-warn-ink">
            <p className="text-sm font-semibold uppercase tracking-wider">
              {store.is_new_store ? "New store · not judged this run" : "Not judged this run"}
            </p>
            <p className="mt-1 text-lg font-semibold leading-snug">{notJudged}</p>
          </div>
        ) : null}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          <div>
            <dt className="text-sm">City</dt>
            <dd className="font-semibold text-ink">{store.city}</dd>
          </div>
          <div>
            <dt className="text-sm">State</dt>
            <dd className="font-semibold text-ink">{store.state}</dd>
          </div>
          <div>
            <dt className="text-sm">Tier</dt>
            <dd className="font-semibold text-ink">{store.tier}</dd>
          </div>
          <div>
            <dt className="text-sm">Opened</dt>
            <dd className="font-semibold text-ink">{formatDate(store.opened_on)}</dd>
          </div>
        </dl>
      </PageTitle>

      <SectionTitle>Store figures</SectionTitle>
      {store.summary.length === 0 ? (
        <EmptyNote>No summary figures were published for this store.</EmptyNote>
      ) : (
        <CheckList checks={store.summary} />
      )}

      <SectionTitle>Alerts this week</SectionTitle>
      {alerts.length === 0 ? (
        <EmptyNote>No alert sent to the area manager this week names this store.</EmptyNote>
      ) : (
        <ul className="space-y-3">
          {alerts.map((alert) => (
            <li key={alert.alert_id} className="rounded-lg border border-line bg-surface p-4">
              <LeverChip lever={alert.lever} />
              <p className="mt-2 font-semibold">{alert.headline}</p>
              {optionalText(alert.definition) ? <Definition>{optionalText(alert.definition)}</Definition> : null}
              <p className="mt-1">{alert.action.text}</p>
              {manager ? (
                <p className="mt-2 text-[0.95rem]">
                  <Link
                    href={`${managerHref(manager.area_manager_id)}#${alertAnchor(alert)}`}
                    className="font-medium underline decoration-line decoration-2 hover:decoration-ink"
                  >
                    See the full alert
                  </Link>
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}

      <SectionTitle>Salesperson cards</SectionTitle>
      {cards.length === 0 ? (
        <EmptyNote>No salesperson cards for this store yet.</EmptyNote>
      ) : (
        <div className="space-y-4">
          {cards.map((card) => (
            <SalespersonCard key={card.card_id} card={card} />
          ))}
        </div>
      )}

      {store.salespeople.length > 0 ? (
        <>
          <SectionTitle>Team</SectionTitle>
          <p>{active.length > 0 ? active.map((p) => p.name).join(", ") : "No active salespeople listed."}</p>
          {inactive.length > 0 ? (
            <p className="mt-1 text-muted">Not active: {inactive.map((p) => p.name).join(", ")}</p>
          ) : null}
        </>
      ) : null}

      <SectionTitle>Data issues at this store</SectionTitle>
      {issues.length === 0 ? (
        <EmptyNote>No data issues were found for this store.</EmptyNote>
      ) : (
        <ul className="space-y-4">
          {issues.map((issue) => (
            <li key={issue.issue_id}>
              <DataIssueItem issue={issue} storeLink={false} knownStores={new Set()} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
