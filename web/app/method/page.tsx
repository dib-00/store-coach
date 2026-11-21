import type { Metadata } from "next";
import Link from "next/link";
import { NoEngineRun, PageTitle, SectionTitle } from "@/components/bits";
import { loadEngineOutput } from "@/lib/data";
import { formatDate } from "@/lib/format";

export const metadata: Metadata = { title: "How the numbers are checked" };

const REPO = "https://github.com/dib-00/store-coach";
const DOC = (path: string) => `${REPO}/blob/main/${path}`;

/** Every figure in the file is a check: an object with id, kind, params, value and display. */
function countChecks(node: unknown): number {
  if (Array.isArray(node)) return node.reduce((n: number, x) => n + countChecks(x), 0);
  if (node && typeof node === "object") {
    const o = node as Record<string, unknown>;
    const self = ["id", "kind", "params", "value", "display"].every((k) => k in o) ? 1 : 0;
    return self + Object.values(o).reduce((n: number, x) => n + countChecks(x), 0);
  }
  return 0;
}

const linkClass = "font-medium text-ink underline decoration-line decoration-2 hover:decoration-ink";

export default function MethodPage() {
  const data = loadEngineOutput();
  if (!data) return <NoEngineRun />;
  const figures = countChecks(data);

  return (
    <>
      <PageTitle title="How the numbers are checked">
        <p>
          Every number on this site comes from Manyavar&apos;s own sales, footfall and roster data by fixed
          rules. No AI writes the figures or the advice: sentences are templates filled with computed
          values.
        </p>
      </PageTitle>

      <section className="space-y-4 leading-relaxed">
        <div className="rounded-lg border border-ink bg-surface px-5 py-4">
          <p className="text-lg font-semibold">
            This run shows {figures.toLocaleString("en-IN")} figures. Each one is recomputed straight from
            the raw data by a separate script before the run is published.
          </p>
          <p className="mt-2">
            The script does not use the engine&apos;s code. It works only from the written recipes and the
            data files, and it stops the daily run if a single figure differs. It also checks that every
            number quoted in an alert has a recipe, that the rupee arithmetic multiplies out, that no
            manager gets more than five alerts, that every card is 60 words or fewer, and that nothing
            after {formatDate(data.as_of)} was used.
          </p>
          <p className="mt-2">
            <a href={DOC("scripts/verify.py")} className={linkClass}>
              The verification script
            </a>{" "}
            ·{" "}
            <a href={DOC("docs/CHECKS.md")} className={linkClass}>
              The recipe for every figure
            </a>
          </p>
        </div>
      </section>

      <SectionTitle>What is compared with what</SectionTitle>
      <ul className="list-disc space-y-2 pl-5 leading-relaxed">
        <li>
          <span className="font-semibold">Same store first, then the city.</span> Never the whole country.
          A salesperson is compared only with colleagues in the same store.
        </li>
        <li>
          <span className="font-semibold">Dated windows.</span> A store is compared with its own 91 days
          before the cause began (for example, the day a strong seller left). Every figure states the
          dates it covers.
        </li>
        <li>
          <span className="font-semibold">The season is not a problem.</span> Footfall doubles every
          October. The engine judges conversion, not footfall, and compares a city with the same weeks
          last year aligned on the festival calendar.
        </li>
        <li>
          <span className="font-semibold">Chance is not a problem.</span> A drop must pass a statistical
          test and be large enough to matter. Small stores get longer windows rather than guesses.
        </li>
      </ul>

      <SectionTitle>Rupees at stake</SectionTitle>
      <p className="leading-relaxed">
        Each alert shows its arithmetic, so it can be checked with a calculator: the gap to a fair
        benchmark, times the weekly volume, times the average value. A store is charged only for what it
        lost beyond the other stores in its city. Discounts are shown as margin given away, not sales
        lost.
      </p>

      <SectionTitle>What is never sent as an alert</SectionTitle>
      <p className="leading-relaxed">
        Numbers that cannot be right, such as a door counter reading zero on days with sales, or one
        customer number on 1,833 bills. These are listed on the{" "}
        <Link href="/data-issues" className={linkClass}>
          data issues
        </Link>{" "}
        page and left out of the figures. An alert is also not sent when the engine cannot name an action
        the store can take today, with who, what and when.
      </p>

      <SectionTitle>Read more</SectionTitle>
      <ul className="list-disc space-y-1 pl-5">
        <li>
          <a href={DOC("docs/METHOD.md")} className={linkClass}>
            Method: the conversion lever, thresholds and back-tests
          </a>
        </li>
        <li>
          <a href={DOC("docs/METHOD-baskets.md")} className={linkClass}>
            Method: bigger baskets
          </a>{" "}
          ·{" "}
          <a href={DOC("docs/METHOD-repeat.md")} className={linkClass}>
            more repeat
          </a>{" "}
          ·{" "}
          <a href={DOC("docs/METHOD-followup.md")} className={linkClass}>
            follow-up
          </a>
        </li>
        <li>
          <a href={DOC("docs/DAILY-RUN.md")} className={linkClass}>
            How the daily run works
          </a>
        </li>
      </ul>
    </>
  );
}
